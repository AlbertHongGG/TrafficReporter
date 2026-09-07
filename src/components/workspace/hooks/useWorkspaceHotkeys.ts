import { useEffect } from 'react';
import type { TimelineClip } from '../../../modules/editor/domain/model';
import { editorWorkspaceTransport } from '../../../modules/editor/application/session/editorSessionSync';

export interface UseWorkspaceHotkeysOptions {
  selectedClip: TimelineClip | null;
  togglePlay: () => void;
  livePlayheadMsRef: React.MutableRefObject<number>;
}

export function useWorkspaceHotkeys({
  selectedClip,
  togglePlay,
  livePlayheadMsRef,
}: UseWorkspaceHotkeysOptions) {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ['input', 'textarea', 'select'].includes(target.tagName.toLowerCase())) {
        return;
      }

      if (event.code === 'Space') {
        event.preventDefault();
        togglePlay();
        return;
      }

      if (event.key === 'Delete' || event.key === 'Backspace') {
        editorWorkspaceTransport.deleteSelectedClips();
      }

      if (event.key.toLowerCase() === 's' && selectedClip) {
        editorWorkspaceTransport.splitClip(selectedClip.id, livePlayheadMsRef.current);
      }

      if (event.key.toLowerCase() === 'm' && selectedClip) {
        editorWorkspaceTransport.setSelectedClipsMuted(!selectedClip.muted);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [livePlayheadMsRef, selectedClip, togglePlay]);
}
