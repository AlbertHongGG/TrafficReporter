import { Header } from '../../components/common/Header/Header';
import { MediaEditorWorkspace } from '../../components/workspace/MainWorkspace';
import { EditorProvider } from '../../components/workspace/EditorContext';
import styles from './AppShell.module.css';

export function AppShell() {
  return (
    <div className="app-container">
      <Header />
      <div className="workspace-content">
        <div className={styles.workspaceHost}>
          <section className={styles.workspacePane}>
            <EditorProvider>
              <MediaEditorWorkspace isActive />
            </EditorProvider>
          </section>
        </div>
      </div>
    </div>
  );
}