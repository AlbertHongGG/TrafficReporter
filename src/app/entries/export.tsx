import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { AppErrorBoundary } from '../../components/AppErrorBoundary';
import { ExportWindow } from '../../modules/export/presentation/ExportWindow';
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