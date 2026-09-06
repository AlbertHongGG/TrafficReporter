import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { AppErrorBoundary } from './components/common/AppErrorBoundary';
import { WindowRouter } from './app/router';
import './index.css';
import { installGlobalLogger } from './utils/logger';

installGlobalLogger();

const rootElement = document.getElementById('root');
if (rootElement) {
  createRoot(rootElement).render(
    <StrictMode>
      <AppErrorBoundary>
        <WindowRouter />
      </AppErrorBoundary>
    </StrictMode>,
  );
}
