import { getCurrentWebviewWindow } from '@tauri-apps/api/webviewWindow';

export type WindowKind = 'main' | 'plate' | 'ai-panel' | 'export';

function isValidWindowKind(value: string | null | undefined): value is WindowKind {
  return value === 'main' || value === 'plate' || value === 'ai-panel' || value === 'export';
}

export function resolveWindowKind(): WindowKind {
  if (typeof window === 'undefined') {
    return 'main';
  }

  // 1. Explicit query parameter (e.g., ?window=plate)
  try {
    const params = new URLSearchParams(window.location.search);
    const queryKind = params.get('window');
    if (isValidWindowKind(queryKind)) {
      return queryKind;
    }
  } catch {
    // Ignore URL parse failures
  }

  // 2. Explicit hash parameter (e.g., #plate)
  try {
    const rawHash = window.location.hash.replace(/^#\/?/, '').split('?')[0];
    if (isValidWindowKind(rawHash)) {
      return rawHash;
    }
  } catch {
    // Ignore hash parse failures
  }

  // 3. Tauri WebviewWindow label inspection
  try {
    const currentWindow = getCurrentWebviewWindow();
    if (currentWindow && isValidWindowKind(currentWindow.label)) {
      return currentWindow.label;
    }
  } catch {
    // Expected when running in standard browser dev mode
  }

  return 'main';
}
