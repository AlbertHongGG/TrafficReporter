/**
 * LPR runtime-status use-case (Phase 4-A, extracted from `useLprWorkflow`).
 *
 * Pure function: inspects the local LPR runtime via infra and stores the
 * result. Never throws: an unreachable runtime is stored as an unavailable
 * status with the failure detail, mirroring the hook.
 */
import {
  defaultLprPorts,
  lprOk,
  type LprPorts,
  type LprResult,
} from './lprPorts.usecase';
import type { LprRuntimeStatus } from '../../domain/lprState';

export async function runLprRefreshRuntimeStatus(
  ports: LprPorts = defaultLprPorts,
): Promise<LprResult<LprRuntimeStatus>> {
  try {
    const runtimeStatus = await ports.getRuntimeStatus();
    ports.actions.setLprRuntimeStatus(runtimeStatus);
    return lprOk(runtimeStatus);
  } catch (error) {
    const fallback: LprRuntimeStatus = {
      available: false,
      pythonExecutable: null,
      runtimeScript: null,
      version: null,
      missingPackages: [],
      installedPackages: [],
      detail: ports.describeError(error, 'Unable to inspect the local LPR runtime.'),
    };
    ports.actions.setLprRuntimeStatus(fallback);
    return lprOk(fallback);
  }
}
