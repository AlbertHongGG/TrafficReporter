import { Header } from '../../components/ui-kit/Header/Header';
import { MediaEditorWorkspace } from '../../components/workspace/MainWorkspace';
import styles from './AppShell.module.css';

export function AppShell() {
  return (
    <div className="app-container">
      <Header />
      <div className="workspace-content">
        <div className={styles.workspaceHost}>
          <section className={styles.workspacePane}>
            <MediaEditorWorkspace isActive />
          </section>
        </div>
      </div>
    </div>
  );
}