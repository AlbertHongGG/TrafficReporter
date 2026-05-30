type TimedJobLike = {
  status: string;
  startedAt: string | null;
  updatedAt: string | null;
};

export const DEFAULT_JOB_STALL_THRESHOLD_MS = 10_000;

function parseTimestamp(value: string | null | undefined) {
  if (!value) {
    return null;
  }

  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

export function buildJobTimingSnapshot(
  job: TimedJobLike,
  nowMs = Date.now(),
  stallThresholdMs = DEFAULT_JOB_STALL_THRESHOLD_MS,
) {
  const startedAtMs = parseTimestamp(job.startedAt);
  const updatedAtMs = parseTimestamp(job.updatedAt) ?? startedAtMs;
  const isActive = job.status === 'queued' || job.status === 'running';
  const totalReferenceMs = isActive ? nowMs : (updatedAtMs ?? nowMs);

  return {
    totalElapsedMs: startedAtMs === null ? null : Math.max(0, totalReferenceMs - startedAtMs),
    idleSinceUpdateMs: isActive && updatedAtMs !== null ? Math.max(0, nowMs - updatedAtMs) : null,
    isStalled: Boolean(isActive && updatedAtMs !== null && nowMs - updatedAtMs >= stallThresholdMs),
  };
}

export function formatElapsedDuration(ms: number | null | undefined) {
  if (ms === null || ms === undefined || Number.isNaN(ms)) {
    return '--';
  }

  const clampedMs = Math.max(0, ms);
  if (clampedMs < 60_000) {
    return `${(clampedMs / 1000).toFixed(1)}s`;
  }

  const totalSeconds = Math.floor(clampedMs / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
  }

  return `${minutes}:${seconds.toString().padStart(2, '0')}`;
}