/**
 * Unified IPC unwrap helper (Blueprint §2.1, Phase 1-B).
 *
 * Converges the scattered per-module `unwrap` / `if (res.status === 'ok')`
 * logic (see `lprApi.ts`, `exportApi.ts`, `aiEvidenceApi.ts`, `aiPanelApi.ts`,
 * `mediaApi.ts`) into a single function that turns a Tauri command result
 * into either the payload or a structured {@link IpcCommandError}.
 *
 * Scope notes:
 * - Dependency-free on purpose — no new npm packages.
 * - No runtime payload validation here; that is Phase 2 (zod) scope.
 * - Full migration of existing API files is Phase 1-D scope; this file only
 *   provides the helper plus one trivial usage example.
 */

/**
 * Shape of every Tauri command result produced by the Specta-generated
 * `typedError` wrapper in `src/types/bindings.ts`.
 */
export type TauriResult<T> =
  | { status: 'ok'; data: T }
  | { status: 'error'; error: string };

/**
 * Structured error thrown when a Tauri command fails.
 *
 * Two failure modes are distinguished:
 * - `command`: the backend reported `{ status: 'error', error }`.
 * - `transport`: the IPC promise itself rejected before a result arrived
 *   (invoke bridge failure, serialization failure, window closed, ...).
 */
export class IpcCommandError extends Error {
  readonly kind: 'command' | 'transport';
  readonly command: string;

  constructor(kind: 'command' | 'transport', command: string, message: string) {
    super(`[${command}] ${message}`);
    this.name = 'IpcCommandError';
    this.kind = kind;
    this.command = command;
  }
}

function toTransportError(command: string, cause: unknown): IpcCommandError {
  if (cause instanceof IpcCommandError) {
    return cause;
  }
  if (cause instanceof Error) {
    return new IpcCommandError('transport', command, `transport failure: ${cause.message}`);
  }
  if (typeof cause === 'string') {
    return new IpcCommandError('transport', command, `transport failure: ${cause}`);
  }
  return new IpcCommandError('transport', command, 'transport failure: unknown error');
}

/**
 * Unwrap a Tauri command result, returning the payload or throwing a
 * structured {@link IpcCommandError}.
 *
 * @param promise - The command promise, resolving to a {@link TauriResult}.
 * @param command - Label used in error messages (defaults to `'tauri-command'`).
 *   Pass the command name (e.g. `'scan_lpr_targets'`) so failures are
 *   attributable without a stack-trace hunt.
 * @returns The `data` payload of a successful result.
 * @throws {IpcCommandError} With `kind: 'command'` when the backend reports
 *   an error, or `kind: 'transport'` when the IPC promise itself rejects.
 *
 * @example
 * ```ts
 * import { commands } from '../../types/bindings';
 * import { unwrapCommand } from '../../infrastructure/ipc-unwrap';
 *
 * export function cancelLprRuntimeJob(): Promise<boolean> {
 *   return unwrapCommand(commands.cancelLprRuntimeJob(), 'cancel_lpr_runtime_job');
 * }
 * ```
 */
export async function unwrapCommand<T>(
  promise: Promise<TauriResult<T>>,
  command = 'tauri-command',
): Promise<T> {
  let result: TauriResult<T>;
  try {
    result = await promise;
  } catch (error: unknown) {
    throw toTransportError(command, error);
  }
  if (result.status === 'ok') {
    return result.data;
  }
  throw new IpcCommandError('command', command, result.error);
}
