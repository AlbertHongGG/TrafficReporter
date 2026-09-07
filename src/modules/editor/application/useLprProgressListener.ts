/**
 * LPR progress listener (Blueprint §4, Phase 4-D).
 *
 * Extracted from `useLprWorkflow`: owns the `listen('editor/lpr-progress')`
 * subscription and folds each event through the `runLprApplyProgressEvent`
 * use-case into the store. Stale payloads (no active request, or a request
 * id that no longer matches) are ignored with no side effects — the
 * stale-ignore semantics live in the use-case, this hook is pure glue.
 */
import { useEffect } from 'react';
import { listen } from '@tauri-apps/api/event';
import type { LprProgress } from '../domain/lprState';
import { defaultLprPorts, type LprPorts } from './usecases/lprPorts.usecase';
import { runLprApplyProgressEvent } from './usecases/lprProgressEvent.usecase';

export function useLprProgressListener(ports: LprPorts = defaultLprPorts): void {
  useEffect(() => {
    let disposed = false;
    let unlisten: (() => void) | undefined;

    void listen<LprProgress>('editor/lpr-progress', (event) => {
      if (disposed) {
        return;
      }
      runLprApplyProgressEvent(
        {
          activeRequestId: ports.getActiveRequestId(),
          payload: event.payload,
        },
        ports,
      );
    }).then((stopListening) => {
      unlisten = stopListening;
    });

    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [ports]);
}
