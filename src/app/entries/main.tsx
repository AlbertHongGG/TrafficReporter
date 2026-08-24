import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { AppErrorBoundary } from '../../components/common/AppErrorBoundary';
import { AppShell } from '../shell/AppShell';
import '../../index.css';
import { installGlobalLogger } from '../../utils/logger';

installGlobalLogger();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppErrorBoundary>
      <AppShell />
    </AppErrorBoundary>
  </StrictMode>,
);