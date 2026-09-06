import { WebviewWindow } from '@tauri-apps/api/webviewWindow';

export function waitForWindowCreation(targetWindow: WebviewWindow, label = 'window'): Promise<WebviewWindow> {
  return new Promise<WebviewWindow>((resolve, reject) => {
    let settled = false;
    let createdCleanup: (() => void) | undefined;
    let errorCleanup: (() => void) | undefined;
    const timeoutId = window.setTimeout(() => {
      settleReject(new Error(`Timed out while creating the ${label} window.`));
    }, 4000);

    const cleanup = () => {
      window.clearTimeout(timeoutId);
      createdCleanup?.();
      errorCleanup?.();
    };

    const settleResolve = () => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      resolve(targetWindow);
    };

    const settleReject = (error: unknown) => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      reject(error instanceof Error ? error : new Error(`Failed to create the ${label} window.`));
    };

    void targetWindow.once('tauri://created', () => {
      settleResolve();
    }).then((unlisten) => {
      createdCleanup = unlisten;
    }).catch((error) => {
      settleReject(error);
    });

    void targetWindow.once<string>('tauri://error', (event) => {
      settleReject(new Error(typeof event.payload === 'string' ? event.payload : `Failed to create the ${label} window.`));
    }).then((unlisten) => {
      errorCleanup = unlisten;
    }).catch((error) => {
      settleReject(error);
    });
  });
}

export async function focusExistingWindow(label: string): Promise<WebviewWindow | null> {
  const existingWindow = await WebviewWindow.getByLabel(label);
  if (existingWindow) {
    await existingWindow.show().catch(() => undefined);
    await existingWindow.setFocus().catch(() => undefined);
    return existingWindow;
  }
  return null;
}
