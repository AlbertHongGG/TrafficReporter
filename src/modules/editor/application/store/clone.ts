import type { EditorFileState, EditorWorkspaceState } from '../../domain/model';

/** Machine-readable code carried by {@link StoreCloneError}. */
export const CLONE_ERROR_CODE = 'CLONE_FAILED' as const;

export type CloneErrorCode = typeof CLONE_ERROR_CODE;

export interface CloneErrorDetails {
  code: CloneErrorCode;
  path: string;
  reason: string;
}

/**
 * Structured error thrown when a store value cannot be deep-cloned.
 * Carries the logical path of the offending value plus the underlying reason
 * so callers (including Wave 2 slices) can report failures without parsing
 * message strings.
 */
export class StoreCloneError extends Error implements CloneErrorDetails {
  readonly code: CloneErrorCode = CLONE_ERROR_CODE;
  readonly path: string;
  readonly reason: string;

  constructor(path: string, reason: string) {
    super(`[store/clone] cannot clone value at "${path}": ${reason}`);
    this.name = 'StoreCloneError';
    this.path = path;
    this.reason = reason;
  }
}

function describeCloneFailure(error: unknown): string {
  if (error instanceof Error && error.message.length > 0) {
    return error.message;
  }
  if (typeof error === 'string' && error.length > 0) {
    return error;
  }
  return 'value is not structured-cloneable (functions, DOM nodes and similar host objects are rejected)';
}

/**
 * Centralized, domain-aware deep clone for the editor store.
 *
 * Baseline is `structuredClone`. Anything it rejects (functions, DOM nodes,
 * …) surfaces as a {@link StoreCloneError} instead of a raw DataCloneError.
 * Only plain data may live in the Zustand store — a clone failure is a
 * programming error and is never swallowed.
 */
export function cloneValue<T>(value: T, path = '<root>'): T {
  try {
    return structuredClone(value);
  } catch (error: unknown) {
    throw new StoreCloneError(path, describeCloneFailure(error));
  }
}

/** Deep-clone a whole workspace (snapshots / cross-window handoff). */
export function cloneWorkspaceState(workspace: EditorWorkspaceState): EditorWorkspaceState {
  return cloneValue(workspace, 'workspace');
}

/** Deep-clone a single file state (per-file snapshot). */
export function cloneFileState(fileState: EditorFileState): EditorFileState {
  return cloneValue(fileState, `files/${fileState.id}`);
}
