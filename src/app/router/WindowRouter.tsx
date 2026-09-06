import React, { useMemo } from 'react';
import { AppShell } from '../shell/AppShell';
import { PlateWindow } from '../../components/lpr-panel/LprWindow';
import { AiEvidenceWindow } from '../../components/ai-panel/AiEvidenceWindow';
import { ExportWindow } from '../../components/export-panel/ExportWindow';
import { resolveWindowKind, type WindowKind } from './windowRouting';

export const WindowRouter: React.FC = () => {
  const windowKind: WindowKind = useMemo(() => resolveWindowKind(), []);

  switch (windowKind) {
    case 'plate':
      return <PlateWindow />;
    case 'ai-panel':
      return <AiEvidenceWindow />;
    case 'export':
      return <ExportWindow />;
    case 'main':
    default:
      return <AppShell />;
  }
};
