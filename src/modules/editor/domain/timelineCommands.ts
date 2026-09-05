import {
  clipDurationMs,
  clipEndMs,
  createId,
  MIN_CLIP_DURATION_MS,
} from './model';
import type { EditorAsset, EditorFileState, TimelineClip } from './model';

const SNAP_THRESHOLD_MS = 120;

function sortByStart(clips: TimelineClip[]) {
  return [...clips].sort((left, right) => {
    if (left.startMs !== right.startMs) {
      return left.startMs - right.startMs;
    }

    return left.id.localeCompare(right.id);
  });
}

function getTrackClips(clips: TimelineClip[], trackId: string, excludeClipId?: string) {
  return sortByStart(
    clips.filter((clip) => clip.trackId === trackId && clip.id !== excludeClipId),
  );
}

function findTrackInsertionStart(
  clips: TimelineClip[],
  trackId: string,
  durationMs: number,
  proposedStartMs: number,
  excludeClipId?: string,
) {
  const trackClips = getTrackClips(clips, trackId, excludeClipId);
  const candidates: Array<{ startMs: number; distance: number }> = [];
  let previousEndMs = 0;

  for (const clip of trackClips) {
    const validMin = previousEndMs;
    const validMax = clip.startMs - durationMs;

    if (validMax >= validMin) {
      const clamped = Math.min(validMax, Math.max(validMin, proposedStartMs));
      candidates.push({
        startMs: clamped,
        distance: Math.abs(clamped - proposedStartMs),
      });
    }

    previousEndMs = clipEndMs(clip);
  }

  const tailStartMs = Math.max(previousEndMs, proposedStartMs);
  candidates.push({
    startMs: tailStartMs,
    distance: Math.abs(tailStartMs - proposedStartMs),
  });

  return candidates.sort((left, right) => left.distance - right.distance)[0]?.startMs ?? 0;
}

function findClip(fileState: EditorFileState, clipId: string) {
  return fileState.clips.find((clip) => clip.id === clipId) ?? null;
}

function sanitizeClipForAsset(clip: TimelineClip, asset: EditorAsset, trackId: string): TimelineClip {
  const assetDurationMs = asset.durationMs ?? 0;
  const inPointMs = Math.min(Math.max(0, clip.inPointMs), Math.max(0, assetDurationMs - MIN_CLIP_DURATION_MS));
  const outPointMs = Math.min(
    assetDurationMs,
    Math.max(inPointMs + MIN_CLIP_DURATION_MS, clip.outPointMs),
  );

  return {
    ...clip,
    assetId: asset.id,
    trackId,
    inPointMs,
    outPointMs,
  };
}

function snapValue(valueMs: number, snapPointsMs: number[]) {
  let closest = valueMs;
  let closestDistance = SNAP_THRESHOLD_MS + 1;

  for (const pointMs of snapPointsMs) {
    if (!Number.isFinite(pointMs) || pointMs < 0) {
      continue;
    }

    const distance = Math.abs(pointMs - valueMs);
    if (distance < closestDistance) {
      closest = pointMs;
      closestDistance = distance;
    }
  }

  return closestDistance <= SNAP_THRESHOLD_MS ? closest : valueMs;
}

function trackBoundaryPoints(fileState: EditorFileState, trackId: string, excludeClipId?: string) {
  const boundaries = [0, fileState.playheadMs];

  for (const clip of getTrackClips(fileState.clips, trackId, excludeClipId)) {
    boundaries.push(clip.startMs, clipEndMs(clip));
  }

  return boundaries;
}

function trackMoveSnapPoints(
  fileState: EditorFileState,
  trackId: string,
  durationMs: number,
  excludeClipId?: string,
) {
  const boundaries = trackBoundaryPoints(fileState, trackId, excludeClipId);
  const snapPoints = [...boundaries];

  for (const boundary of boundaries) {
    snapPoints.push(boundary - durationMs);
  }

  return snapPoints;
}

function withClips(
  fileState: EditorFileState,
  clips: TimelineClip[],
  selectedClipIds = fileState.selectedClipIds,
) {
  return {
    ...fileState,
    clips,
    selectedClipIds,
    isPlaying: false,
  };
}

function previousClip(fileState: EditorFileState, clip: TimelineClip) {
  return getTrackClips(fileState.clips, clip.trackId, clip.id)
    .filter((candidate) => candidate.startMs < clip.startMs)
    .at(-1) ?? null;
}

function nextClip(fileState: EditorFileState, clip: TimelineClip) {
  return getTrackClips(fileState.clips, clip.trackId, clip.id)
    .find((candidate) => candidate.startMs >= clip.startMs) ?? null;
}

export function moveClip(
  fileState: EditorFileState,
  clipId: string,
  startMs: number,
) {
  const clip = findClip(fileState, clipId);
  if (!clip) {
    return fileState;
  }

  const trackId = fileState.track.id;
  const snappedStartMs = snapValue(
    Math.max(0, startMs),
    trackMoveSnapPoints(fileState, trackId, clipDurationMs(clip), clip.id),
  );
  const resolvedStartMs = findTrackInsertionStart(
    fileState.clips,
    trackId,
    clipDurationMs(clip),
    snappedStartMs,
    clip.id,
  );

  return withClips(
    fileState,
    fileState.clips.map((candidate) =>
      candidate.id === clipId
        ? { ...candidate, trackId, startMs: resolvedStartMs }
        : candidate,
    ),
  );
}

export function trimClipStart(
  fileState: EditorFileState,
  clipId: string,
  proposedInPointMs: number,
) {
  const clip = findClip(fileState, clipId);
  if (!clip) {
    return fileState;
  }

  let nextInPointMs = Math.min(
    clip.outPointMs - MIN_CLIP_DURATION_MS,
    Math.max(0, proposedInPointMs),
  );
  let nextStartMs = clip.startMs + (nextInPointMs - clip.inPointMs);
  const snappedStartMs = snapValue(
    nextStartMs,
    trackBoundaryPoints(fileState, clip.trackId, clip.id),
  );
  if (snappedStartMs !== nextStartMs) {
    nextInPointMs = clip.inPointMs + (snappedStartMs - clip.startMs);
    nextInPointMs = Math.min(
      clip.outPointMs - MIN_CLIP_DURATION_MS,
      Math.max(0, nextInPointMs),
    );
    nextStartMs = clip.startMs + (nextInPointMs - clip.inPointMs);
  }
  const previous = previousClip(fileState, clip);

  if (previous) {
    const minStartMs = clipEndMs(previous);
    if (nextStartMs < minStartMs) {
      const delta = minStartMs - nextStartMs;
      nextStartMs = minStartMs;
      if (nextInPointMs + delta > clip.outPointMs - MIN_CLIP_DURATION_MS) {
        return fileState;
      }
      return withClips(
        fileState,
        fileState.clips.map((candidate) =>
          candidate.id === clipId
            ? {
                ...candidate,
                startMs: nextStartMs,
                inPointMs: nextInPointMs + delta,
              }
            : candidate,
        ),
      );
    }
  }

  return withClips(
    fileState,
    fileState.clips.map((candidate) =>
      candidate.id === clipId
        ? { ...candidate, startMs: nextStartMs, inPointMs: nextInPointMs }
        : candidate,
    ),
  );
}

export function trimClipEnd(
  fileState: EditorFileState,
  clipId: string,
  proposedOutPointMs: number,
) {
  const clip = findClip(fileState, clipId);
  if (!clip) {
    return fileState;
  }

  const maxByAsset = fileState.asset.durationMs ?? 0;
  const next = nextClip(fileState, clip);
  const maxByTrack = next
    ? clip.inPointMs + Math.max(MIN_CLIP_DURATION_MS, next.startMs - clip.startMs)
    : maxByAsset;
  let nextOutPointMs = Math.min(
    Math.max(clip.inPointMs + MIN_CLIP_DURATION_MS, proposedOutPointMs),
    Math.min(maxByAsset, maxByTrack),
  );

  const snappedEndMs = snapValue(
    clip.startMs + (nextOutPointMs - clip.inPointMs),
    trackBoundaryPoints(fileState, clip.trackId, clip.id),
  );
  if (snappedEndMs !== clip.startMs + (nextOutPointMs - clip.inPointMs)) {
    nextOutPointMs = clip.inPointMs + (snappedEndMs - clip.startMs);
    nextOutPointMs = Math.min(
      Math.max(clip.inPointMs + MIN_CLIP_DURATION_MS, nextOutPointMs),
      Math.min(maxByAsset, maxByTrack),
    );
  }

  return withClips(
    fileState,
    fileState.clips.map((candidate) =>
      candidate.id === clipId
        ? { ...candidate, outPointMs: nextOutPointMs }
        : candidate,
    ),
  );
}

export function splitClipAt(fileState: EditorFileState, clipId: string, atMs: number) {
  const clip = findClip(fileState, clipId);
  if (!clip) {
    return fileState;
  }

  const localOffsetMs = atMs - clip.startMs;
  if (
    localOffsetMs <= MIN_CLIP_DURATION_MS
    || clipDurationMs(clip) - localOffsetMs <= MIN_CLIP_DURATION_MS
  ) {
    return fileState;
  }

  const splitInPointMs = clip.inPointMs + localOffsetMs;
  const rightClip: TimelineClip = {
    ...clip,
    id: createId('clip'),
    startMs: atMs,
    inPointMs: splitInPointMs,
  };

  return withClips(
    fileState,
    fileState.clips.flatMap((candidate) => {
      if (candidate.id !== clip.id) {
        return [candidate];
      }

      return [
        {
          ...candidate,
          outPointMs: splitInPointMs,
        },
        rightClip,
      ];
    }),
    [rightClip.id],
  );
}

export function deleteSelectedClips(fileState: EditorFileState) {
  if (fileState.selectedClipIds.length === 0) {
    return fileState;
  }

  return withClips(
    fileState,
    fileState.clips.filter((clip) => !fileState.selectedClipIds.includes(clip.id)),
    [],
  );
}

export function setSelectedClipMuted(fileState: EditorFileState, muted: boolean) {
  if (fileState.selectedClipIds.length === 0) {
    return fileState;
  }

  return withClips(
    fileState,
    fileState.clips.map((clip) =>
      fileState.selectedClipIds.includes(clip.id) ? { ...clip, muted } : clip,
    ),
  );
}

export function setTrackMuted(fileState: EditorFileState, muted: boolean) {
  if (fileState.clips.length === 0 || fileState.clips.every((clip) => clip.muted === muted)) {
    return fileState;
  }

  return withClips(
    fileState,
    fileState.clips.map((clip) => ({
      ...clip,
      muted,
    })),
  );
}

export function relinkFileAsset(fileState: EditorFileState, nextAsset: EditorAsset) {
  return {
    ...fileState,
    asset: {
      ...nextAsset,
      id: fileState.asset.id,
    },
    clips: fileState.clips.map((clip) =>
      sanitizeClipForAsset(clip, { ...nextAsset, id: fileState.asset.id }, fileState.track.id),
    ),
    isPlaying: false,
  };
}
