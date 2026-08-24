import React, { useMemo } from 'react';
import {
  Pause,
  Play,
  Scissors,
  SkipBack,
  SkipForward,
  Trash2,
  Volume2,
  VolumeX,
} from 'lucide-react';
import { useEditorContext } from '../workspace/EditorContext';
import { formatRulerLabel, getTimelineDuration } from '../../modules/editor/domain/model';
import styles from '../workspace/MainWorkspace.module.css';

interface TransportRowProps {
  currentTimecodeRef: React.RefObject<HTMLSpanElement | null>;
  displayPlayheadMs: number;
  livePlayheadMsRef: React.MutableRefObject<number>;
  seekBy: (ms: number) => void;
  togglePlay: () => void;
}

export const TransportRow: React.FC<TransportRowProps> = ({
  currentTimecodeRef,
  displayPlayheadMs,
  livePlayheadMsRef,
  seekBy,
  togglePlay,
}) => {
  const { state, dispatch } = useEditorContext();
  const activeFile = state.activeFileId ? state.files.find(f => f.id === state.activeFileId) : null;

  const activeClips = useMemo(() => activeFile?.clips ?? [], [activeFile]);
  const selectedClipId = activeFile?.selectedClipIds[0] ?? null;
  const selectedClip = useMemo(
    () => activeClips.find((clip) => clip.id === selectedClipId) ?? null,
    [activeClips, selectedClipId],
  );
  
  const trackMuted = useMemo(
    () => activeClips.length > 0 && activeClips.every((clip) => clip.muted),
    [activeClips],
  );
  
  const timelineDurationMs = useMemo(() => getTimelineDuration(activeClips), [activeClips]);
  const currentIsPlaying = activeFile?.isPlaying ?? false;
  const currentPreviewMuted = activeFile?.previewMuted ?? false;
  const currentPreviewVolume = activeFile?.previewVolume ?? 0.85;

  return (
    <div className={styles.transportRow}>
      <div className={styles.transportLeftGroup}>
        <div className={styles.transportTime}>
          <span ref={currentTimecodeRef as React.RefObject<HTMLSpanElement>} className={styles.timecode}>
            {formatRulerLabel(displayPlayheadMs)}
          </span>
          <span className={styles.timecodeDivider}>/</span>
          <span className={styles.timecodeDuration}>
            {formatRulerLabel(timelineDurationMs)}
          </span>
        </div>
        <div className={styles.toolbarDivider} />
        <div className={styles.timelineActions}>
          <button
            type="button"
            className={`${styles.iconButton} ${trackMuted ? styles.iconButtonActive : ''}`}
            onClick={() => dispatch({ type: 'set-track-muted', muted: !trackMuted })}
            disabled={!activeFile || activeClips.length === 0}
            aria-pressed={trackMuted}
            aria-label={trackMuted ? 'Unmute track' : 'Mute track'}
          >
            {trackMuted ? <VolumeX size={14} /> : <Volume2 size={14} />}
          </button>
          <button
            type="button"
            className={styles.iconButton}
            onClick={() =>
              dispatch({
                type: 'split-clip',
                clipId: selectedClip?.id ?? '',
                atMs: livePlayheadMsRef.current,
              })
            }
            disabled={!selectedClip}
            aria-label="Split selected clip"
          >
            <Scissors size={14} />
          </button>
          <button
            type="button"
            className={styles.iconButton}
            onClick={() => dispatch({ type: 'delete-selected-clips' })}
            disabled={!selectedClip}
            aria-label="Delete selected clip"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      <div className={styles.transportButtons}>
        <button
          type="button"
          className={styles.iconButton}
          onClick={() => seekBy(-1000)}
          disabled={timelineDurationMs === 0}
          aria-label="Seek backward one second"
        >
          <SkipBack size={16} />
        </button>
        <button
          type="button"
          className={styles.transportPrimary}
          onClick={togglePlay}
          disabled={timelineDurationMs === 0}
          aria-label={currentIsPlaying ? 'Pause playback' : 'Start playback'}
        >
          {currentIsPlaying ? (
            <Pause size={18} />
          ) : (
            <Play size={18} className={styles.playIconOffset} />
          )}
        </button>
        <button
          type="button"
          className={styles.iconButton}
          onClick={() => seekBy(1000)}
          disabled={timelineDurationMs === 0}
          aria-label="Seek forward one second"
        >
          <SkipForward size={16} />
        </button>
      </div>

      <div className={styles.volumeGroup}>
        <button
          type="button"
          className={styles.iconButton}
          onClick={() =>
            dispatch({ type: 'set-preview-muted', previewMuted: !currentPreviewMuted })
          }
          disabled={!activeFile}
          aria-label={currentPreviewMuted ? 'Unmute preview' : 'Mute preview'}
        >
          {currentPreviewMuted ? <VolumeX size={14} /> : <Volume2 size={14} />}
        </button>
        <input
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={currentPreviewVolume}
          onChange={(event) =>
            dispatch({
              type: 'set-preview-volume',
              previewVolume: Number(event.target.value),
            })
          }
          disabled={!activeFile}
          aria-label="Adjust preview volume"
          className={styles.volumeSlider}
        />
      </div>
    </div>
  );
};
