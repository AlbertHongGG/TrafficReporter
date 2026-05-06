import React from 'react';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { Clapperboard, Minus, Square, X } from 'lucide-react';
import styles from './Header.module.css';

export const Header: React.FC = () => {
  const minimize = () => getCurrentWindow().minimize();
  const toggleMaximize = () => getCurrentWindow().toggleMaximize();
  const close = () => getCurrentWindow().close();

  return (
    <div data-tauri-drag-region className={styles.header}>
      <div className={styles.left} data-tauri-drag-region>
        <div className={styles.logo} data-tauri-drag-region>
          <div className={styles.logoIcon}>
            <Clapperboard size={12} />
          </div>
          <span className={styles.logoText}>Traffic Editor</span>
        </div>
      </div>

      <div className={styles.center} data-tauri-drag-region>
        <div className={styles.workspaceBadge}>Video Workspace</div>
      </div>

      <div className={styles.right}>
        <button className={styles.controlBtn} onClick={minimize} aria-label="Minimize window">
          <Minus size={14} />
        </button>
        <button className={styles.controlBtn} onClick={toggleMaximize} aria-label="Toggle maximize window">
          <Square size={12} />
        </button>
        <button className={`${styles.controlBtn} ${styles.closeBtn}`} onClick={close} aria-label="Close application">
          <X size={14} />
        </button>
      </div>
    </div>
  );
};
