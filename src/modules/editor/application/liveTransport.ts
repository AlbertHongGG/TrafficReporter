export type LiveTransportMode = 'paused' | 'scrubbing' | 'playing';

export interface LiveTransportSnapshot {
  playheadMs: number;
  mode: LiveTransportMode;
  updatedAt: string;
}

export interface LiveTransportStore {
  getSnapshot: () => LiveTransportSnapshot;
  subscribe: (listener: () => void) => () => void;
  publish: (snapshot: LiveTransportSnapshot) => void;
  reset: (snapshot?: Partial<LiveTransportSnapshot>) => void;
}

function normalizePlayheadMs(playheadMs: number) {
  return Math.max(0, Math.round(playheadMs));
}

function sameTransportPosition(left: LiveTransportSnapshot, right: LiveTransportSnapshot) {
  return left.playheadMs === right.playheadMs && left.mode === right.mode;
}

export function buildLiveTransportSnapshot(
  playheadMs: number,
  mode: LiveTransportMode,
  updatedAt = new Date().toISOString(),
): LiveTransportSnapshot {
  return {
    playheadMs: normalizePlayheadMs(playheadMs),
    mode,
    updatedAt,
  };
}

export function resolveLiveTransportMode(playing: boolean, scrubbing = false): LiveTransportMode {
  if (playing) {
    return 'playing';
  }
  if (scrubbing) {
    return 'scrubbing';
  }
  return 'paused';
}

export function resolveEffectivePlayheadMs(
  committedPlayheadMs: number,
  liveTransport: Pick<LiveTransportSnapshot, 'playheadMs'> | null | undefined,
) {
  return liveTransport?.playheadMs ?? committedPlayheadMs;
}

export function createLiveTransportStore(
  initialSnapshot: Partial<LiveTransportSnapshot> = {},
): LiveTransportStore {
  let snapshot = buildLiveTransportSnapshot(
    initialSnapshot.playheadMs ?? 0,
    initialSnapshot.mode ?? 'paused',
    initialSnapshot.updatedAt,
  );
  const listeners = new Set<() => void>();

  const notify = () => {
    listeners.forEach((listener) => listener());
  };

  return {
    getSnapshot: () => snapshot,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    publish(nextSnapshot) {
      if (sameTransportPosition(snapshot, nextSnapshot)) {
        snapshot = nextSnapshot;
        return;
      }

      snapshot = nextSnapshot;
      notify();
    },
    reset(nextSnapshot = {}) {
      const resetSnapshot = buildLiveTransportSnapshot(
        nextSnapshot.playheadMs ?? 0,
        nextSnapshot.mode ?? 'paused',
        nextSnapshot.updatedAt,
      );
      const changed = !sameTransportPosition(snapshot, resetSnapshot);
      snapshot = resetSnapshot;
      if (changed) {
        notify();
      }
    },
  };
}