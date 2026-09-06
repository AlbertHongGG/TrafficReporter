import { describe, expect, it } from 'vitest';
import { createEditorSessionStoreState, reduceEditorSessionStoreState } from './sessionStore';

describe('sessionStore', () => {
  it('increments the session revision when the workspace changes', () => {
    const initialState = createEditorSessionStoreState();
    const nextState = reduceEditorSessionStoreState(initialState, {
      type: 'set-lpr-runtime-status',
      runtimeStatus: {
        available: true,
        pythonExecutable: 'python',
        runtimeScript: 'runtime.py',
        version: '1.0.0',
        missingPackages: [],
        installedPackages: [],
        detail: 'ok',
      },
    });

    expect(nextState.revision).toBe(initialState.revision + 1);
    expect(nextState.workspace.analysis.lprRuntimeStatus?.available).toBe(true);
  });

  it('keeps the same revision when the reducer returns the same workspace object', () => {
    const initialState = createEditorSessionStoreState();
    const nextState = reduceEditorSessionStoreState(initialState, {
      type: 'set-active-file',
      fileId: 'missing-file',
    });

    expect(nextState).toBe(initialState);
  });
});
