/**
 * LPR interval-editing use-cases (Phase 4-A, extracted from `useLprWorkflow`).
 *
 * Pure functions: suggest the working interval (explicit session interval,
 * else selected/at-playhead clip, else ±1s around the playhead), set an
 * In/Out boundary from the live playhead, or adopt the current clip range.
 */
import {
  clipDurationMs,
  findClipAtPlayhead,
  type TimelineIntervalSelection,
} from '../../domain/model';
import { normalizeLprInterval } from '../../domain/lprWorkflowHelpers';
import {
  defaultLprPorts,
  lprErr,
  lprOk,
  lprSkipped,
  type LprPorts,
  type LprResult,
} from './lprPorts.usecase';

export interface LprIntervalEditingInput {
  /** Live playhead in ms (owned by the hook's ref; not read from the store). */
  playheadMs: number;
}

/** Resolve the working interval without dispatching (mirrors the hook helper). */
export function suggestLprInterval(
  input: LprIntervalEditingInput,
  ports: LprPorts = defaultLprPorts,
): TimelineIntervalSelection {
  const file = ports.readActiveFile();
  const session = ports.readLprSession();
  const playheadMs = input.playheadMs;

  if (session.interval) {
    return normalizeLprInterval(session.interval);
  }

  const activeClips = file?.clips ?? [];
  const selectedClip = file?.selectedClipIds[0]
    ? activeClips.find((clip) => clip.id === file.selectedClipIds[0])
    : null;
  const currentClip = selectedClip ?? findClipAtPlayhead(activeClips, playheadMs);
  if (currentClip) {
    return normalizeLprInterval({
      startMs: currentClip.startMs,
      endMs: currentClip.startMs + clipDurationMs(currentClip),
    });
  }

  return normalizeLprInterval({
    startMs: Math.max(0, playheadMs - 1000),
    endMs: playheadMs + 1000,
  });
}

export interface LprSetIntervalBoundaryInput extends LprIntervalEditingInput {
  boundary: 'start' | 'end';
}

export function runLprSetIntervalBoundary(
  input: LprSetIntervalBoundaryInput,
  ports: LprPorts = defaultLprPorts,
): LprResult<TimelineIntervalSelection> {
  const currentInterval = suggestLprInterval(input, ports);
  const next = normalizeLprInterval({
    startMs: input.boundary === 'start' ? input.playheadMs : currentInterval.startMs,
    endMs: input.boundary === 'end' ? input.playheadMs : currentInterval.endMs,
  });
  ports.actions.setLprInterval(next);
  return lprOk(next);
}

export function runLprUseClipInterval(
  input: LprIntervalEditingInput,
  ports: LprPorts = defaultLprPorts,
): LprResult<TimelineIntervalSelection> {
  const file = ports.readActiveFile();
  const activeClips = file?.clips ?? [];
  const selectedClip = file?.selectedClipIds[0]
    ? activeClips.find((clip) => clip.id === file.selectedClipIds[0])
    : null;
  const currentClip = selectedClip ?? findClipAtPlayhead(activeClips, input.playheadMs);
  if (!currentClip) {
    return lprErr(lprSkipped('No clip under the playhead for interval adoption.', 'lpr-interval-editing'));
  }
  const next = normalizeLprInterval({
    startMs: currentClip.startMs,
    endMs: currentClip.startMs + clipDurationMs(currentClip),
  });
  ports.actions.setLprInterval(next);
  return lprOk(next);
}
