export interface RevisionedWindowSnapshot<TSnapshot> {
  revision: number;
  generatedAt: string;
  snapshot: TSnapshot;
}

export function createRevisionedWindowSnapshot<TSnapshot>(
  snapshot: TSnapshot,
  revision: number,
  generatedAt = new Date().toISOString(),
): RevisionedWindowSnapshot<TSnapshot> {
  return {
    revision: Math.max(0, Math.trunc(revision)),
    generatedAt,
    snapshot,
  };
}

export function isRevisionedWindowSnapshot<TSnapshot>(value: unknown): value is RevisionedWindowSnapshot<TSnapshot> {
  if (!value || typeof value !== 'object') {
    return false;
  }
  const candidate = value as Partial<RevisionedWindowSnapshot<TSnapshot>>;
  return typeof candidate.revision === 'number' && 'snapshot' in candidate;
}

export function unwrapRevisionedWindowSnapshot<TSnapshot>(
  value: TSnapshot | RevisionedWindowSnapshot<TSnapshot>,
): RevisionedWindowSnapshot<TSnapshot> {
  if (isRevisionedWindowSnapshot<TSnapshot>(value)) {
    return value;
  }
  return createRevisionedWindowSnapshot(value, 0, '');
}

export function shouldApplyRevisionedWindowSnapshot(currentRevision: number, nextRevision: number) {
  return nextRevision >= currentRevision;
}
