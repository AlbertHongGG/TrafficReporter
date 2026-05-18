import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { AppErrorBoundary } from '../../components/AppErrorBoundary';
import { AiEvidenceWindow } from '../../modules/editor/presentation/AiEvidenceWindow';
import '../../index.css';
import { installGlobalLogger } from '../../utils/logger';

installGlobalLogger();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppErrorBoundary>
      <AiEvidenceWindow />
    </AppErrorBoundary>
  </StrictMode>,
);