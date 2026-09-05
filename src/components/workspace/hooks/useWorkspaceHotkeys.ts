import { useEffect } from 'react';
import type { TimelineClip } from '../../../modules/editor/domain/model';
import type { EditorAction } from '../../../modules/editor/application/editorReducer';

export interface UseWorkspaceHotkeysOptions {
  selectedClip: TimelineClip | null;
  togglePlay: () => void;
  dispatch: React.Dispatch<EditorAction>;
  livePlayheadMsRef: React.MutableRefObject<number>;
}

export function useWorkspaceHotkeys({
  selectedClip,
  togglePlay,
  dispatch,
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
        dispatch({ type: 'delete-selected-clips' });
      }

      if (event.key.toLowerCase() === 's' && selectedClip) {
        dispatch({ type: 'split-clip', clipId: selectedClip.id, atMs: livePlayheadMsRef.current });
      }

      if (event.key.toLowerCase() === 'm' && selectedClip) {
        dispatch({ type: 'set-selected-clips-muted', muted: !selectedClip.muted });
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [dispatch, livePlayheadMsRef, selectedClip, togglePlay]);
}
