import React from 'react';
import {
  Archive,
  Brain,
  FileOutput,
  ImageDown,
  Import,
  Target,
} from 'lucide-react';
import type { EditorFileState } from '../../modules/editor/domain/model';
import styles from './MainWorkspace.module.css';

interface ToolbarProps {
  activeFile: EditorFileState | null;
  onExportCurrentFrame: () => void;
  onOpenExportWindow: () => void;
  onOpenPlateWindow: () => void;
  onOpenAiPanelWindow: () => void;
  onToggleCompactExports: () => void;
  onImportClick: () => void;
}

export const Toolbar: React.FC<ToolbarProps> = ({
  activeFile,
  onExportCurrentFrame,
  onOpenExportWindow,
  onOpenPlateWindow,
  onOpenAiPanelWindow,
  onToggleCompactExports,
  onImportClick,
}) => {
  return (
    <section className={styles.toolbar}>
      <div className={styles.toolbarActions}>
        <button
          type="button"
          className={styles.toolbarButton}
          onClick={() => void onExportCurrentFrame()}
          disabled={!activeFile || activeFile.asset.status !== 'ready'}
        >
          <ImageDown size={14} />
          Frame
        </button>
        <button type="button" className={styles.toolbarButton} onClick={() => void onOpenExportWindow()}>
          <FileOutput size={14} />
          Export
        </button>
        <button type="button" className={styles.toolbarButton} onClick={() => void onOpenPlateWindow()}>
          <Target size={14} />
          Plate
        </button>
        <button type="button" className={styles.toolbarButton} onClick={() => void onOpenAiPanelWindow()}>
          <Brain size={14} />
          AI
        </button>
        <button
          type="button"
          className={`${styles.toolbarButton} ${activeFile?.renderProfile.compressionMode === 'compact' ? styles.toolbarButtonActive : ''}`}
          onClick={onToggleCompactExports}
          disabled={!activeFile}
        >
          <Archive size={14} />
          Compact
        </button>
        <button type="button" className={styles.primaryButton} onClick={() => void onImportClick()}>
          <Import size={14} />
          Import
        </button>
      </div>
    </section>
  );
};
