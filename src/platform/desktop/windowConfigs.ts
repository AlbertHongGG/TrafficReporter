export type DesktopWindowId = 'main' | 'plate' | 'ai-panel' | 'export';

export interface DesktopWindowConfig {
  label: DesktopWindowId;
  title: string;
  url: string;
  width: number;
  height: number;
  minWidth?: number;
  minHeight?: number;
  resizable?: boolean;
  center?: boolean;
  decorations?: boolean;
  transparent?: boolean;
}

export const MAIN_WINDOW_LABEL: DesktopWindowId = 'main';
export const PLATE_WINDOW_LABEL: DesktopWindowId = 'plate';
export const AI_PANEL_WINDOW_LABEL: DesktopWindowId = 'ai-panel';
export const EXPORT_WINDOW_LABEL: DesktopWindowId = 'export';

export const DESKTOP_WINDOW_CONFIGS: Record<Exclude<DesktopWindowId, 'main'>, DesktopWindowConfig> = {
  plate: {
    label: 'plate',
    title: 'Plate',
    url: 'index.html?window=plate',
    width: 720,
    height: 860,
    minWidth: 720,
    minHeight: 560,
    resizable: true,
    center: true,
    decorations: false,
    transparent: false,
  },
  'ai-panel': {
    label: 'ai-panel',
    title: 'AI Evidence',
    url: 'index.html?window=ai-panel',
    width: 980,
    height: 760,
    minWidth: 720,
    minHeight: 560,
    resizable: true,
    center: true,
    decorations: false,
    transparent: false,
  },
  export: {
    label: 'export',
    title: 'Export Settings',
    url: 'index.html?window=export',
    width: 800,
    height: 720,
    minWidth: 700,
    minHeight: 680,
    resizable: true,
    center: true,
    decorations: false,
    transparent: false,
  },
};
