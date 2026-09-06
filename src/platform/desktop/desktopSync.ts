export interface VersionedPayload<T> {
  version: number;
  timestamp: string;
  payload: T;
}

export function createVersionedPayload<T>(
  payload: T,
  version: number,
  timestamp = new Date().toISOString(),
): VersionedPayload<T> {
  return {
    version: Math.max(0, Math.trunc(version)),
    timestamp,
    payload,
  };
}

export function isVersionedPayload<T>(value: unknown): value is VersionedPayload<T> {
  if (!value || typeof value !== 'object') {
    return false;
  }
  const candidate = value as Partial<VersionedPayload<T>>;
  return typeof candidate.version === 'number' && 'payload' in candidate;
}

export function unwrapVersionedPayload<T>(
  value: T | VersionedPayload<T>,
): VersionedPayload<T> {
  if (isVersionedPayload<T>(value)) {
    return value;
  }
  return createVersionedPayload(value, 0, '');
}

export function shouldApplyVersion(currentVersion: number, nextVersion: number): boolean {
  return nextVersion >= currentVersion;
}
