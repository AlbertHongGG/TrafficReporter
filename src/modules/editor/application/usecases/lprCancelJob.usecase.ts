/**
 * LPR job-cancel use-case (Phase 4-A, extracted from `useLprWorkflow`).
 *
 * Pure function: marks the in-flight request cancelled, moves the job to
 * `cancelled`, asks the runtime to cancel, and reconciles success/failure.
 * A failed cancel unmarks the request and moves the job to `failed` with
 * reason `cancel-failed`, mirroring the hook. Never throws.
 */
import {
  commitLprJobUpdate,
  defaultLprPorts,
  lprErr,
  lprOk,
  toLprUsecaseError,
  type LprPorts,
  type LprResult,
} from './lprPorts.usecase';

export interface LprCancelJobData {
  requestId: string | null;
  cancelled: boolean;
}

export async function runLprCancelJob(
  ports: LprPorts = defaultLprPorts,
): Promise<LprResult<LprCancelJobData>> {
  const requestId = ports.getActiveRequestId();
  if (!requestId) {
    return lprOk({ requestId: null, cancelled: false });
  }

  const stage = ports.readLprSession().job.stage || 'LPR';
  ports.markCancelled(requestId);
  commitLprJobUpdate(ports, {
    status: 'cancelled',
    stage,
    detail: 'Cancelling current LPR task.',
    error: null,
    reasonCode: null,
  });

  try {
    await ports.cancelRuntimeJob();
    ports.clearActiveRequest(requestId);
    commitLprJobUpdate(ports, {
      status: 'cancelled',
      progress: 1,
      stage,
      detail: 'Current LPR task cancelled.',
      error: null,
      reasonCode: null,
    });
    return lprOk({ requestId, cancelled: true });
  } catch (error) {
    ports.unmarkCancelled(requestId);
    ports.logError('Cancel LPR job failed.', error);
    const summary = ports.describeError(error, 'Unable to cancel the current LPR task.');
    commitLprJobUpdate(ports, {
      status: 'failed',
      progress: 1,
      stage,
      detail: 'Unable to cancel the current LPR task.',
      error: summary,
      reasonCode: 'cancel-failed',
    });
    ports.notifyFeedback(summary);
    return lprErr(toLprUsecaseError(error, 'cancel_lpr_runtime_job', 'Unable to cancel the current LPR task.', 'cancel-failed'));
  }
}
