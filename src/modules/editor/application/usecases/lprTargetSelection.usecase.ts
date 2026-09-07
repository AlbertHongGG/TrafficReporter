/**
 * LPR target-selection use-case (Phase 4-A, extracted from `useLprWorkflow`).
 *
 * Pure function: anchors the chosen target track at the preferred (or live)
 * playhead, selects it in the store, seeks the playhead, and pauses playback.
 */
import { buildLprTargetAnchor } from '../../domain/lprState';
import {
  defaultLprPorts,
  lprOk,
  type LprPorts,
  type LprResult,
} from './lprPorts.usecase';
import type { LprTargetAnchor } from '../../domain/lprState';

export interface LprSelectTargetTrackInput {
  targetTrackId: string;
  /** Live playhead in ms (owned by the hook's ref; not read from the store). */
  playheadMs: number;
  preferredTimeMs?: number | null;
}

export interface LprSelectTargetTrackData {
  targetTrackId: string;
  anchor: LprTargetAnchor | null;
  playheadMs: number;
  wasPlaying: boolean;
}

export function runLprSelectTargetTrack(
  input: LprSelectTargetTrackInput,
  ports: LprPorts = defaultLprPorts,
): LprResult<LprSelectTargetTrackData> {
  const session = ports.readLprSession();
  const targetTrack = session.targetTracks.find((track) => track.id === input.targetTrackId) ?? null;
  const playheadMs = Math.max(0, Math.round(input.playheadMs));
  const anchor = buildLprTargetAnchor(
    targetTrack,
    Math.max(0, Math.round(input.preferredTimeMs ?? input.playheadMs)),
  );

  ports.actions.selectLprTargetTrack(input.targetTrackId, anchor);
  ports.actions.setPlayhead(playheadMs);
  const wasPlaying = ports.readIsPlaying();
  if (wasPlaying) {
    ports.actions.setPlaying(false);
  }
  return lprOk({ targetTrackId: input.targetTrackId, anchor, playheadMs, wasPlaying });
}
