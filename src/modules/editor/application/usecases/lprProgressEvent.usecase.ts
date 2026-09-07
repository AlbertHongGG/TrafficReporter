/**
 * LPR progress-event use-case (Phase 4-A, extracted from `useLprWorkflow`).
 *
 * Pure function: folds one `editor/lpr-progress` payload into a job update.
 * The `listen()` subscription itself stays in the Wave 2 hook
 * (`useLprProgressListener` per Blueprint §4); the hook calls this for the
 * event body. Stale payloads (other request / no active request) are skipped.
 */
import type { LprProgress } from '../../domain/lprState';
import {
  buildLprJobUpdateFromProgress,
  shouldApplyLprProgress,
} from '../lprProgress';
import {
  commitLprJobUpdate,
  defaultLprPorts,
  lprOk,
  type LprPorts,
  type LprResult,
} from './lprPorts.usecase';

export interface LprProgressEventInput {
  activeRequestId: string | null;
  payload: LprProgress;
}

export interface LprProgressEventData {
  applied: boolean;
}

export function runLprApplyProgressEvent(
  input: LprProgressEventInput,
  ports: LprPorts = defaultLprPorts,
): LprResult<LprProgressEventData> {
  if (!shouldApplyLprProgress(input.activeRequestId, input.payload)) {
    return lprOk({ applied: false });
  }
  commitLprJobUpdate(
    ports,
    buildLprJobUpdateFromProgress(input.activeRequestId, input.payload),
  );
  return lprOk({ applied: true });
}
