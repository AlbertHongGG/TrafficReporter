import { Header } from '../../components/Header/Header';
import { MediaEditorWorkspace } from '../../modules/editor/presentation/MediaEditorWorkspace';
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