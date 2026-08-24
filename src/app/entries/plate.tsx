import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { AppErrorBoundary } from '../../components/common/AppErrorBoundary';
import { PlateWindow } from '../../components/lpr-panel/LprWindow';
import '../../index.css';
import { installGlobalLogger } from '../../utils/logger';

installGlobalLogger();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppErrorBoundary>
      <PlateWindow />
    </AppErrorBoundary>
  </StrictMode>,
);
