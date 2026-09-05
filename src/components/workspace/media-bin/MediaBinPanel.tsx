import React from 'react';
import { AlertCircle, Film, Import, Link2, Trash2 } from 'lucide-react';
import { formatTransportTime, type EditorFileState } from '../../../modules/editor/domain/model';
import { useEditorContext } from '../EditorContext';
import styles from '../MainWorkspace.module.css';

interface MediaBinPanelProps {
  isExternalDropActive: boolean;
  missingFiles: EditorFileState[];
  handleImportClick: () => void;
  handleSelectFile: (fileId: string) => void;
  handleRelinkFile: (fileId: string) => void;
  handleRemoveFile: (fileId: string) => void;
}

export const MediaBinPanel: React.FC<MediaBinPanelProps> = ({
  isExternalDropActive,
  missingFiles,
  handleImportClick,
  handleSelectFile,
  handleRelinkFile,
  handleRemoveFile,
}) => {
  const { state } = useEditorContext();

  return (
    <aside className={styles.binPanel}>
      {isExternalDropActive && (
        <div className={styles.dropOverlay}>
          <div className={styles.dropOverlayContent}>
            <Import size={32} />
            <strong>Drop Videos Here</strong>
          </div>
        </div>
      )}

      <div className={styles.panelHeader}>
        <h2>Files</h2>
        <span className={styles.badge}>{state.files.length}</span>
      </div>

      {missingFiles.length > 0 && (
        <div className={styles.missingSummary}>
          <AlertCircle size={15} />
          <span>{missingFiles.length} file(s) missing. Relink them before playback or export.</span>
        </div>
      )}

      <div className={styles.assetList}>
        {state.files.length === 0 && (
          <button type="button" className={styles.emptyState} onClick={() => void handleImportClick()}>
            <Import size={20} />
          </button>
        )}

        {state.files.map((fileState) => (
          <div
            key={fileState.id}
            className={`${styles.assetCard} ${fileState.asset.status === 'missing' ? styles.assetCardMissing : ''} ${state.activeFileId === fileState.id ? styles.assetCardSelected : ''}`}
          >
            <button
              type="button"
              className={styles.assetDragButton}
              onClick={() => handleSelectFile(fileState.id)}
            >
              <div className={styles.assetVisual}>
                {fileState.asset.thumbnailUrl ? (
                  <img src={fileState.asset.thumbnailUrl} alt={fileState.asset.name} />
                ) : (
                  <div className={styles.assetFallback}>
                    <Film size={16} />
                  </div>
                )}
              </div>
              <div className={styles.assetMeta}>
                <strong>{fileState.asset.name}</strong>
                <span>{formatTransportTime(fileState.asset.durationMs ?? 0)}</span>
                <span>{fileState.asset.status === 'missing' ? 'Missing file' : `${fileState.clips.length} segment(s)`}</span>
              </div>
            </button>

            <div className={styles.assetActions}>
              {fileState.asset.status === 'missing' ? (
                <button type="button" className={styles.iconButton} onClick={() => void handleRelinkFile(fileState.id)}>
                  <Link2 size={14} />
                </button>
              ) : null}
              <button type="button" className={styles.iconButton} onClick={() => handleRemoveFile(fileState.id)}>
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
};
