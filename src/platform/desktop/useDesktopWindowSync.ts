import { useEffect, useRef, useState } from 'react';
import { listen } from '@tauri-apps/api/event';
import { shouldApplyVersion } from './desktopSync';

function unwrapSyncPayload<T>(value: unknown): { data: T; version: number } {
  if (value && typeof value === 'object') {
    const candidate = value as Record<string, unknown>;
    if ('version' in candidate && 'payload' in candidate) {
      return { data: candidate.payload as T, version: Number(candidate.version) || 0 };
    }
    if ('revision' in candidate && 'snapshot' in candidate) {
      return { data: candidate.snapshot as T, version: Number(candidate.revision) || 0 };
    }
  }
  return { data: value as T, version: 0 };
}

export interface UseDesktopWindowSyncOptions<T> {
  eventName: string;
  initialState: T;
  onRequestInitialState?: () => void | Promise<unknown>;
}

export function useDesktopWindowSync<T>({
  eventName,
  initialState,
  onRequestInitialState,
}: UseDesktopWindowSyncOptions<T>): [T, React.Dispatch<React.SetStateAction<T>>, number] {
  const [state, setState] = useState<T>(initialState);
  const [currentVersion, setCurrentVersion] = useState(0);
  const versionRef = useRef(0);

  useEffect(() => {
    let active = true;

    if (onRequestInitialState) {
      void onRequestInitialState();
    }

    const unlistenPromise = listen(eventName, (event) => {
      if (!active) return;
      const { data, version } = unwrapSyncPayload<T>(event.payload);

      if (!shouldApplyVersion(versionRef.current, version)) {
        return;
      }

      versionRef.current = version;
      setCurrentVersion(version);
      setState(data);
    });

    return () => {
      active = false;
      void unlistenPromise.then((unlisten) => unlisten());
    };
  }, [eventName]);

  return [state, setState, currentVersion];
}
