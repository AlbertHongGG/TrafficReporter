import { emitTo } from '@tauri-apps/api/event';
import { WebviewWindow } from '@tauri-apps/api/webviewWindow';
import {
  DESKTOP_WINDOW_CONFIGS,
  MAIN_WINDOW_LABEL,
  type DesktopWindowId,
} from './windowConfigs';
import { createVersionedPayload, type VersionedPayload } from './desktopSync';

function waitForWindowCreation(targetWindow: WebviewWindow, label: string): Promise<WebviewWindow> {
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
      if (settled) return;
      settled = true;
      cleanup();
      resolve(targetWindow);
    };

    const settleReject = (error: unknown) => {
      if (settled) return;
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

export class DesktopWindowManager {
  async get(windowId: DesktopWindowId): Promise<WebviewWindow | null> {
    return WebviewWindow.getByLabel(windowId);
  }

  async focus(windowId: DesktopWindowId): Promise<WebviewWindow | null> {
    const existing = await this.get(windowId);
    if (existing) {
      await existing.show().catch(() => undefined);
      await existing.setFocus().catch(() => undefined);
      return existing;
    }
    return null;
  }

  async open(windowId: Exclude<DesktopWindowId, 'main'>): Promise<WebviewWindow> {
    const existing = await this.focus(windowId);
    if (existing) {
      return existing;
    }

    const config = DESKTOP_WINDOW_CONFIGS[windowId];
    if (!config) {
      throw new Error(`Unregistered desktop window configuration: ${windowId}`);
    }

    const newWindow = new WebviewWindow(config.label, {
      url: config.url,
      title: config.title,
      width: config.width,
      height: config.height,
      minWidth: config.minWidth,
      minHeight: config.minHeight,
      resizable: config.resizable ?? true,
      center: config.center ?? true,
      decorations: config.decorations ?? false,
      transparent: config.transparent ?? false,
      focus: true,
    });

    return waitForWindowCreation(newWindow, config.label);
  }

  async close(windowId: DesktopWindowId): Promise<void> {
    const existing = await this.get(windowId);
    if (existing) {
      await existing.close().catch(() => undefined);
    }
  }

  async broadcast<T>(
    targetWindowId: DesktopWindowId,
    event: string,
    payload: T,
    version = 0,
  ): Promise<void> {
    const versioned: VersionedPayload<T> = createVersionedPayload(payload, version);
    return emitTo(targetWindowId, event, versioned);
  }

  async sendToMain<T>(event: string, payload: T): Promise<void> {
    return emitTo(MAIN_WINDOW_LABEL, event, payload);
  }

  async send<T>(targetWindowId: DesktopWindowId, event: string, payload: T): Promise<void> {
    return emitTo(targetWindowId, event, payload);
  }
}

export const desktopWindowManager = new DesktopWindowManager();
