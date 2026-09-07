/**
 * LPR evidence-export use-case (Phase 4-A, extracted from `useLprWorkflow`).
 *
 * Pure function: exports the evidence bundle to an already-resolved output
 * path. The file dialog stays in the Wave 2 hook — the hook passes the
 * user-confirmed path in; path normalization (`.json` suffix) lives here.
 */
import { resolveLprDisplayCandidate } from '../plateWindow';
import {
  defaultLprPorts,
  lprErr,
  lprOk,
  lprSkipped,
  readReadyFile,
  toLprUsecaseError,
  type LprPorts,
  type LprResult,
} from './lprPorts.usecase';
import type { LprEvidenceExportResponse } from '../../domain/lprState';

export interface LprExportEvidenceInput {
  /** User-confirmed output path (from the hook's save dialog). */
  selectedPath: string;
  /** Live playhead in ms (owned by the hook's ref; not read from the store). */
  playheadMs: number;
}

export function resolveLprEvidenceOutputPath(selectedPath: string): string {
  return selectedPath.toLowerCase().endsWith('.json') ? selectedPath : `${selectedPath}.json`;
}

export async function runLprExportEvidence(
  input: LprExportEvidenceInput,
  ports: LprPorts = defaultLprPorts,
): Promise<LprResult<LprEvidenceExportResponse>> {
  const file = readReadyFile(ports);
  const session = ports.readLprSession();
  const topCandidate = resolveLprDisplayCandidate(
    session.candidates,
    session.review,
    session.acceptedCandidateId,
  );
  if (!file || (!topCandidate && session.samples.length === 0)) {
    return lprErr(lprSkipped('Nothing to export: no ready media or LPR results.', 'export_lpr_evidence'));
  }

  try {
    const response = await ports.exportEvidence({
      outputPath: resolveLprEvidenceOutputPath(input.selectedPath),
      sourcePath: file.asset.path,
      timeMs: Math.max(0, Math.round(input.playheadMs)),
      markerRect: file.markerRect,
      compressionMode: file.renderProfile.compressionMode,
      interval: session.interval,
      targetTrack: session.analysisTrack ?? session.targetTracks.find(
        (track) => track.id === session.selectedTargetTrackId,
      ) ?? null,
      acceptedCandidate: topCandidate,
      candidates: session.candidates,
      samples: session.samples,
      review: session.review,
      provenance: session.lastAnalysisProvenance,
    });
    ports.notifyFeedback(
      `Evidence bundle exported to ${response.bundleDir} with ${response.decisionFrameCount} decision frames and ${response.exportedFileCount} files.`,
    );
    return lprOk(response);
  } catch (error) {
    ports.logError('Failed to export LPR evidence.', error);
    const summary = ports.describeError(error, 'Unable to export the LPR evidence snapshot.');
    ports.notifyFeedback(summary);
    return lprErr(toLprUsecaseError(error, 'export_lpr_evidence', 'Unable to export the LPR evidence snapshot.'));
  }
}
