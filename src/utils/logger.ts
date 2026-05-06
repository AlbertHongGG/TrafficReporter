type LogLevel = 'debug' | 'info' | 'warn' | 'error';
type ConsoleMethod = 'log' | 'info' | 'warn' | 'error';

interface SerializedError {
  name: string;
  message: string;
  stack?: string;
  cause?: unknown;
  extra?: Record<string, unknown>;
}

const LOG_COLORS: Record<LogLevel, string> = {
  debug: 'color: #94a3b8',
  info: 'color: #facc15',
  warn: 'color: #fb923c; font-weight: 600',
  error: 'color: #f87171; font-weight: 700',
};

const PREFIX = '[MediaEditor]';
const originalConsole = {
  log: console.log.bind(console),
  info: console.info.bind(console),
  warn: console.warn.bind(console),
  error: console.error.bind(console),
};

let globalLoggerInstalled = false;

function formatTimestamp(): string {
  return new Date().toLocaleTimeString('en-US', {
    hour12: false,
  });
}

function methodForLevel(level: LogLevel): ConsoleMethod {
  if (level === 'debug') {
    return 'log';
  }

  return level;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

export function getErrorMessage(error: unknown, fallback = 'Unexpected error.'): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }

  if (typeof error === 'string' && error.trim()) {
    return error;
  }

  if (isRecord(error) && typeof error.message === 'string' && error.message.trim()) {
    return error.message;
  }

  return fallback;
}

export function serializeError(error: unknown): SerializedError | { value: unknown } {
  if (error instanceof Error) {
    const extraEntries = Object.entries(error).filter(([key]) => !['name', 'message', 'stack', 'cause'].includes(key));
    return {
      name: error.name,
      message: error.message,
      stack: error.stack,
      cause: 'cause' in error ? (error as Error & { cause?: unknown }).cause : undefined,
      extra: extraEntries.length > 0 ? Object.fromEntries(extraEntries) : undefined,
    };
  }

  if (typeof error === 'string') {
    return {
      name: 'Error',
      message: error,
    };
  }

  return { value: error };
}

function write(level: LogLevel, module: string, message: string, ...data: unknown[]) {
  const timestamp = formatTimestamp();
  const style = LOG_COLORS[level];
  const tag = `${PREFIX}[${module}][${level.toUpperCase()}]`;
  originalConsole[methodForLevel(level)](`%c${timestamp} ${tag} ${message}`, style, ...data);
}

function writeIntercept(level: 'warn' | 'error', args: unknown[]) {
  const timestamp = formatTimestamp();
  const style = LOG_COLORS[level];
  const label = `${PREFIX}[Console][${level.toUpperCase()}]`;
  originalConsole[level](`%c${timestamp} ${label}`, style, ...args);
}

export function createLogger(module: string) {
  return {
    debug: (message: string, ...data: unknown[]) => write('debug', module, message, ...data),
    info: (message: string, ...data: unknown[]) => write('info', module, message, ...data),
    warn: (message: string, ...data: unknown[]) => write('warn', module, message, ...data),
    error: (message: string, ...data: unknown[]) => write('error', module, message, ...data),
  };
}

export function installGlobalLogger() {
  if (globalLoggerInstalled || typeof window === 'undefined') {
    return;
  }

  globalLoggerInstalled = true;
  const log = createLogger('Global');

  window.addEventListener('error', (event) => {
    log.error('Unhandled window error.', {
      message: event.message,
      filename: event.filename,
      lineno: event.lineno,
      colno: event.colno,
      error: serializeError(event.error),
    });
  });

  window.addEventListener('unhandledrejection', (event) => {
    log.error('Unhandled promise rejection.', serializeError(event.reason));
  });

  console.warn = (...args: unknown[]) => {
    writeIntercept('warn', args);
  };

  console.error = (...args: unknown[]) => {
    writeIntercept('error', args);
  };

  log.info('Global logger installed.');
}

export type Logger = ReturnType<typeof createLogger>;
