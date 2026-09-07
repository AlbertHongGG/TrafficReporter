/**
 * LPR target-scan use-case (Phase 4-A, extracted from `useLprWorkflow`).
 *
 * Pure function: calls the infra scan API, decides store dispatches, and
 * returns a unified result. Request tracking (supersede/cancel) flows through
 * ports so tests can drive stale-completion semantics deterministically.
 */
import { buildTargetTracksFromDetections } from '../../domain/lprWorkflowHelpers';
import type { LprWorkflowMode } from '../../domain/lprState';
import {
  commitLprJobUpdate,
  defaultLprPorts,
  lprErr,
  lprOk,
  lprSkipped,
  lprStaleError,
  readReadyFile,
  toLprUsecaseError,
  type LprPorts,
  type LprResult,
} from './lprPorts.usecase';

export interface LprScanTargetsInput {
  /** Live playhead in ms (owned by the hook's ref; not read from the store). */
  playheadMs: number;
}

export interface LprScanTargetsData {
  requestId: string;
  detectionCount: number;
  workflowMode: LprWorkflowMode;
}

export async function runLprScanTargets(
  input: LprScanTargetsInput,
  ports: LprPorts = defaultLprPorts,
): Promise<LprResult<LprScanTargetsData>> {
  const file = readReadyFile(ports);
  if (!file) {
    return lprErr(lprSkipped('No ready media file for target scan.', 'scan_lpr_targets'));
  }

  const session = ports.readLprSession();
  const requestId = ports.beginRequest('Targets', 'Scanning current frame for trackable targets.', 0.18);

  try {
    const response = await ports.scanTargets({
      sourcePath: file.asset.path,
      timeMs: Math.max(0, Math.round(input.playheadMs)),
      markerRect: file.markerRect,
      targetVehicleKind: session.targetVehicleKind,
      requestId,
    });

    if (ports.isStale(requestId)) {
      ports.forgetRequest(requestId);
      return lprErr(lprStaleError(requestId, 'scan_lpr_targets'));
    }

    const workflowMode: LprWorkflowMode = response.detections.length > 0 ? 'target' : 'range';
    ports.actions.setLprRuntimeStatus(response.runtime);
    ports.actions.setLprTargetTracks(buildTargetTracksFromDetections(response.detections));
    ports.actions.setLprAnalysisTrack(null);
    ports.actions.setLprMode(workflowMode);
    commitLprJobUpdate(ports, {
      status: 'completed',
      progress: 1,
      stage: 'Targets',
      detail: response.detections.length > 0
        ? `${response.detections.length} target(s) ready.`
        : 'No target found in the current frame.',
    });
    ports.forgetRequest(requestId);
    return lprOk({ requestId, detectionCount: response.detections.length, workflowMode });
  } catch (error) {
    if (ports.isStale(requestId)) {
      ports.forgetRequest(requestId);
      return lprErr(lprStaleError(requestId, 'scan_lpr_targets'));
    }
    ports.logError('Target scan failed.', error);
    const summary = ports.describeError(error, 'Unable to scan targets.');
    commitLprJobUpdate(ports, {
      status: 'failed',
      progress: 1,
      stage: 'Targets',
      detail: 'Target scan failed.',
      error: summary,
    });
    ports.notifyFeedback(summary);
    ports.forgetRequest(requestId);
    return lprErr(toLprUsecaseError(error, 'scan_lpr_targets', 'Unable to scan targets.'));
  }
}
