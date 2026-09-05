import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { AppErrorBoundary } from '../../components/common/AppErrorBoundary';
import { ExportWindow } from '../../components/export-panel/ExportWindow';
import '../../index.css';
import { installGlobalLogger } from '../../utils/logger';

installGlobalLogger();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppErrorBoundary>
      <ExportWindow />
    </AppErrorBoundary>
  </StrictMode>,
);