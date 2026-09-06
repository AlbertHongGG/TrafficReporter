import { buildDefaultAnalysisState, type EditorAnalysisState } from './analysisState';
import type {
  EditorAsset,
  LprDecisionTrace,
  LprJobStatus,
  LprLegibilityLevel,
  LprTrackingTier,
  LprVehicleKind,
} from '../../../types/bindings';
import type {
  AudioBitrateKbps,
  ExportFormat,
  OutputCompressionMode,
  RenderProfile,
  VideoQuality,
} from '../../export/domain/model';
import type { LprTargetTrack, LprTrackedRegion } from './lprState';

// Core Timeline & Media Entities
export interface VideoMarkerRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface TimelineIntervalSelection {
  startMs: number;
  endMs: number;
}

export interface TimelineClip {
  id: string;
  assetId: string;
  trackId: string;
  startMs: number;
  inPointMs: number;
  outPointMs: number;
  muted: boolean;
}

export interface TimelineTrack {
  id: string;
  name: string;
  order: number;
}

export interface MediaProbeResult {
  durationMs: number;
  hasVideo: boolean;
  hasAudio: boolean;
  fps?: number;
  audioBitrateKbps?: number;
  width?: number;
  height?: number;
}

export type MediaKind = 'video';

export interface MediaAssetRecord extends MediaProbeResult {
  id: string;
  name: string;
  path: string;
  kind: MediaKind;
}

export type OperationFeedbackScope = 'import' | 'workspace' | 'export' | 'playback';

export interface OperationFeedback {
  scope: OperationFeedbackScope;
  message: string;
}

// Re-exports for Export Domain
export type { AudioBitrateKbps, ExportFormat, OutputCompressionMode, RenderProfile, VideoQuality };

// Re-exports for LPR Domain
export type {
  LprAnalysisProfileCatalog,
  LprAnalysisProfileDefinition,
  LprAnalysisProfileId,
} from './lprProfiles';

export type {
  LprAnalysisProvenance,
  LprEvidenceExportRequest,
  LprEvidenceExportResponse,
  LprFrameAnalysisRequest,
  LprFrameAnalysisResponse,
  LprFrameSample,
  LprIntervalAnalysisRequest,
  LprIntervalAnalysisResponse,
  LprJobState,
  LprPlateCandidate,
  LprProgress,
  LprProgressPayload,
  LprQualityMetrics,
  LprResultHistoryEntry,
  LprReviewState,
  LprRuntimeStatus,
  LprSessionState,
  LprTargetAnchor,
  LprTargetScanRequest,
  LprTargetScanResponse,
  LprTargetTrack,
  LprTrackedRegion,
  LprWorkflowMode,
} from './lprState';

// Re-exports for AI Evidence Domain
export type {
  AiEvidenceJobState,
  AiEvidenceKeyframe,
  AiEvidenceOverlayBox,
  AiEvidencePixelBox,
  AiEvidenceProgress,
  AiEvidenceProgressKind,
  AiEvidenceProgressPayload,
  AiEvidenceRequest,
  AiEvidenceResponse,
  AiEvidenceSessionState,
  AiEvidenceSharedProjection,
  AiEvidenceTargetSelection,
  AiEvidenceTimelineFrameRef,
  AiEvidenceToolCall,
} from './aiEvidenceState';

// Re-exports from Specta Bindings
export type {
  EditorAsset,
  LprDecisionTrace,
  LprJobStatus,
  LprLegibilityLevel,
  LprTrackingTier,
  LprVehicleKind,
};

export type AssetStatus = 'ready' | 'missing';

export interface EditorFilePayload {
  id: string;
  asset: EditorAsset;
  track: TimelineTrack;
  clips: TimelineClip[];
  renderProfile: RenderProfile;
}

export interface EditorFileState extends EditorFilePayload {
  selectedClipIds: string[];
  playheadMs: number;
  zoom: number;
  previewVolume: number;
  previewMuted: boolean;
  isPlaying: boolean;
  markerRect: VideoMarkerRect | null;
}

export interface EditorWorkspacePayload {
  workspaceName: string;
  activeFileId: string | null;
  files: EditorFilePayload[];
  analysis: EditorAnalysisState;
}

export interface EditorWorkspaceState {
  workspaceName: string;
  activeFileId: string | null;
  files: EditorFileState[];
  analysis: EditorAnalysisState;
}

export const DEFAULT_WORKSPACE_NAME = 'Video Workspace';

export const DEFAULT_RENDER_PROFILE: RenderProfile = {
  format: 'mp4',
  fps: 60,
  videoQuality: 'source',
  audioBitrateKbps: 320,
  compressionMode: 'standard',
};

const AUDIO_BITRATE_OPTIONS_DESC: AudioBitrateKbps[] = [320, 256, 192, 128, 96];

function resolveDefaultAudioBitrateKbps(sourceBitrateKbps?: number): AudioBitrateKbps {
  if (!Number.isFinite(sourceBitrateKbps) || !sourceBitrateKbps || sourceBitrateKbps <= 0) {
    return DEFAULT_RENDER_PROFILE.audioBitrateKbps ?? 320;
  }

  const normalizedSourceBitrateKbps = Math.round(sourceBitrateKbps);
  return AUDIO_BITRATE_OPTIONS_DESC.find((option) => option <= normalizedSourceBitrateKbps)
    ?? AUDIO_BITRATE_OPTIONS_DESC[AUDIO_BITRATE_OPTIONS_DESC.length - 1];
}

export const DEFAULT_ZOOM = 96;

export const MIN_ZOOM = 0.5;

export const MAX_ZOOM = 2400;

export const MIN_CLIP_DURATION_MS = 120;

export const DEFAULT_MARKER_RECT: VideoMarkerRect = {
  x: 0.24,
  y: 0.24,
  width: 0.32,
  height: 0.24,
};

export function createId(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}

export function createRunFolderId() {
  const now = new Date();
  const year = (now.getFullYear() % 100).toString().padStart(2, '0');
  const month = (now.getMonth() + 1).toString().padStart(2, '0');
  const day = now.getDate().toString().padStart(2, '0');
  const hours = now.getHours().toString().padStart(2, '0');
  const minutes = now.getMinutes().toString().padStart(2, '0');
  const seconds = now.getSeconds().toString().padStart(2, '0');
  const randomBytes = crypto.getRandomValues(new Uint8Array(4));
  const randomSuffix = Array.from(randomBytes)
    .map((value) => value.toString(16).padStart(2, '0'))
    .join('');

  return `${year}${month}${day}-${hours}${minutes}${seconds}-${randomSuffix}`;
}

export function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export function clampUnit(value: number) {
  return clamp(value, 0, 1);
}

export function basename(path: string) {
  return path.split(/[\\/]/).filter(Boolean).at(-1) ?? path;
}

export function extensionOf(path: string) {
  const fileName = basename(path);
  const dotIndex = fileName.lastIndexOf('.');
  return dotIndex === -1 ? '' : fileName.slice(dotIndex + 1).toLowerCase();
}

export function detectMediaKind(path: string, probe?: Pick<MediaProbeResult, 'hasVideo'>) {
  const extension = extensionOf(path);
  if (probe?.hasVideo || ['mp4', 'mkv', 'mov', 'webm', 'avi', 'm4v'].includes(extension)) {
    return 'video';
  }

  return 'video';
}

export function clipDurationMs(clip: TimelineClip) {
  return Math.max(0, clip.outPointMs - clip.inPointMs);
}

export function clipEndMs(clip: TimelineClip) {
  return clip.startMs + clipDurationMs(clip);
}

export function msToPx(milliseconds: number, zoom: number) {
  return (milliseconds / 1000) * zoom;
}

export function pxToMs(pixels: number, zoom: number) {
  return (pixels / zoom) * 1000;
}

export function formatTransportTime(milliseconds: number) {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
  }

  return `${minutes}:${seconds.toString().padStart(2, '0')}`;
}

export function formatRulerLabel(milliseconds: number) {
  const totalMilliseconds = Math.max(0, Math.round(milliseconds));
  const totalSeconds = Math.floor(totalMilliseconds / 1000);
  const millisecondsPart = totalMilliseconds % 1000;
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const baseLabel = hours > 0
    ? `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`
    : `${minutes}:${seconds.toString().padStart(2, '0')}`;

  if (millisecondsPart === 0) {
    return baseLabel;
  }

  return `${baseLabel}.${millisecondsPart.toString().padStart(3, '0')}`;
}

export function formatRulerLabelWithMilliseconds(milliseconds: number) {
  const totalMilliseconds = Math.max(0, Math.round(milliseconds));
  const totalSeconds = Math.floor(totalMilliseconds / 1000);
  const millisecondsPart = totalMilliseconds % 1000;
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const baseLabel = hours > 0
    ? `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`
    : `${minutes}:${seconds.toString().padStart(2, '0')}`;

  return `${baseLabel}.${millisecondsPart.toString().padStart(3, '0')}`;
}

export function getTimelineDuration(clips: TimelineClip[]) {
  if (clips.length === 0) {
    return 0;
  }

  return clips.reduce((maxValue, clip) => Math.max(maxValue, clipEndMs(clip)), 0);
}

export function normalizeMarkerRect(markerRect: VideoMarkerRect) {
  const x = clampUnit(markerRect.x);
  const y = clampUnit(markerRect.y);
  const maxWidth = Math.max(0.05, 1 - x);
  const maxHeight = Math.max(0.05, 1 - y);

  return {
    x,
    y,
    width: clamp(markerRect.width, 0.05, maxWidth),
    height: clamp(markerRect.height, 0.05, maxHeight),
  } satisfies VideoMarkerRect;
}

export function createSingleTrack(trackId = createId('track')): TimelineTrack {
  return {
    id: trackId,
    name: 'Track 1',
    order: 1,
  };
}

export function createDefaultClip(assetId: string, trackId: string, durationMs: number): TimelineClip {
  return {
    id: `clip-${assetId}`,
    assetId,
    trackId,
    startMs: 0,
    inPointMs: 0,
    outPointMs: Math.max(MIN_CLIP_DURATION_MS, durationMs),
    muted: false,
  };
}

export interface BuildEditorFileStateOptions {
  id?: string;
  track?: TimelineTrack;
  clips?: TimelineClip[];
  renderProfile?: RenderProfile;
  markerRect?: VideoMarkerRect | null;
}

export function buildEditorFileState(asset: EditorAsset, options: BuildEditorFileStateOptions = {}): EditorFileState {
  const track = options.track ? { ...options.track } : createSingleTrack(`track-${asset.id}`);
  const clips = options.clips?.length
    ? options.clips.map((clip) => ({ ...clip }))
    : [createDefaultClip(asset.id, track.id, asset.durationMs ?? 0)];
  const defaultFps = asset.fps ?? DEFAULT_RENDER_PROFILE.fps;
  const defaultAudioBitrateKbps = resolveDefaultAudioBitrateKbps(asset.audioBitrateKbps ?? undefined);

  return {
    id: options.id ?? `file-${asset.id}`,
    asset,
    track,
    clips,
    renderProfile: {
      ...DEFAULT_RENDER_PROFILE,
      fps: defaultFps,
      audioBitrateKbps: defaultAudioBitrateKbps,
      ...options.renderProfile,
    },
    selectedClipIds: [],
    playheadMs: 0,
    zoom: DEFAULT_ZOOM,
    previewVolume: 0.85,
    previewMuted: false,
    isPlaying: false,
    markerRect: options.markerRect ? normalizeMarkerRect(options.markerRect) : null,
  };
}

export function buildDefaultWorkspaceState(): EditorWorkspaceState {
  return {
    workspaceName: DEFAULT_WORKSPACE_NAME,
    activeFileId: null,
    files: [],
    analysis: buildDefaultAnalysisState(),
  };
}

export function getActiveFile(state: EditorWorkspaceState) {
  if (!state.activeFileId) {
    return null;
  }

  return state.files.find((file) => file.id === state.activeFileId) ?? null;
}

export function findClosestTrackFrame(
  track: Pick<LprTargetTrack, 'frames'>,
  playheadMs: number,
  toleranceMs = 360,
): LprTrackedRegion | null {
  const { frames } = track;
  if (frames.length === 0) {
    return null;
  }

  let low = 0;
  let high = frames.length - 1;

  while (low <= high) {
    const mid = (low + high) >> 1;
    const frameTimeMs = frames[mid].timeMs;
    if (frameTimeMs === playheadMs) {
      return frames[mid];
    }
    if (frameTimeMs < playheadMs) {
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }

  const rightIndex = Math.min(low, frames.length - 1);
  const leftIndex = Math.max(0, high);
  const leftFrame = frames[leftIndex];
  const rightFrame = frames[rightIndex];
  const closestFrame = Math.abs(leftFrame.timeMs - playheadMs) <= Math.abs(rightFrame.timeMs - playheadMs)
    ? leftFrame
    : rightFrame;

  return Math.abs(closestFrame.timeMs - playheadMs) <= toleranceMs ? closestFrame : null;
}

export function clampNormalizedRect(markerRect: VideoMarkerRect): VideoMarkerRect {
  const x1 = clampUnit(markerRect.x);
  const y1 = clampUnit(markerRect.y);
  const x2 = clamp(markerRect.x + markerRect.width, x1, 1);
  const y2 = clamp(markerRect.y + markerRect.height, y1, 1);

  return {
    x: x1,
    y: y1,
    width: Math.max(0, x2 - x1),
    height: Math.max(0, y2 - y1),
  };
}

function interpolateNormalizedRect(left: VideoMarkerRect, right: VideoMarkerRect, ratio: number): VideoMarkerRect {
  return clampNormalizedRect({
    x: left.x + ((right.x - left.x) * ratio),
    y: left.y + ((right.y - left.y) * ratio),
    width: left.width + ((right.width - left.width) * ratio),
    height: left.height + ((right.height - left.height) * ratio),
  });
}

export function resolveTrackFrameAtPlayhead(
  track: Pick<LprTargetTrack, 'frames'>,
  playheadMs: number,
  toleranceMs = 360,
  maxInterpolationGapMs = 260,
): LprTrackedRegion | null {
  const { frames } = track;
  if (frames.length === 0) {
    return null;
  }

  let low = 0;
  let high = frames.length - 1;

  while (low <= high) {
    const mid = (low + high) >> 1;
    const frameTimeMs = frames[mid].timeMs;
    if (frameTimeMs === playheadMs) {
      return frames[mid];
    }
    if (frameTimeMs < playheadMs) {
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }

  const rightIndex = Math.min(low, frames.length - 1);
  const leftIndex = Math.max(0, high);
  const leftFrame = frames[leftIndex];
  const rightFrame = frames[rightIndex];
  const closestFrame = Math.abs(leftFrame.timeMs - playheadMs) <= Math.abs(rightFrame.timeMs - playheadMs)
    ? leftFrame
    : rightFrame;

  const interpolationGapMs = rightFrame.timeMs - leftFrame.timeMs;
  const shouldInterpolate = (
    leftFrame !== rightFrame
    && playheadMs > leftFrame.timeMs
    && playheadMs < rightFrame.timeMs
    && interpolationGapMs > 0
    && interpolationGapMs <= maxInterpolationGapMs
  );

  if (shouldInterpolate) {
    const ratio = (playheadMs - leftFrame.timeMs) / interpolationGapMs;
    return {
      id: `${leftFrame.id}:${rightFrame.id}:${Math.round(playheadMs)}`,
      timeMs: playheadMs,
      box: interpolateNormalizedRect(leftFrame.box, rightFrame.box, ratio),
      confidence: leftFrame.confidence + ((rightFrame.confidence - leftFrame.confidence) * ratio),
      className: leftFrame.className,
      diagnostics: {
        ...(leftFrame.diagnostics ?? {}),
        interpolated: true,
        interpolationWindowMs: interpolationGapMs,
        interpolationSourceTimes: [leftFrame.timeMs, rightFrame.timeMs],
      },
    };
  }

  return Math.abs(closestFrame.timeMs - playheadMs) <= toleranceMs ? closestFrame : null;
}

export function findClipAtPlayhead(clips: TimelineClip[], playheadMs: number) {
  return clips.find((clip) => playheadMs >= clip.startMs && playheadMs < clipEndMs(clip)) ?? null;
}

export function getSourceTimeAtPlayhead(file: EditorFileState, playheadMs: number) {
  const clip = findClipAtPlayhead(file.clips, playheadMs);
  if (!clip) {
    return null;
  }

  return clamp(
    clip.inPointMs + (playheadMs - clip.startMs),
    0,
    file.asset.durationMs ?? 0,
  );
}
