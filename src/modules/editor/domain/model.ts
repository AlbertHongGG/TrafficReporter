import type {
  MediaProbeResult,
  MediaAssetRecord,
  RenderProfile,
  TimelineClip,
  TimelineTrack,
  VideoMarkerRect,
} from '../../../shared/contracts';

export type { AudioBitrateKbps, VideoQuality } from '../../../shared/contracts';

export type {
  MediaProbeResult,
  MediaAssetRecord,
  RenderProfile,
  TimelineClip,
  TimelineTrack,
  VideoMarkerRect,
} from '../../../shared/contracts';

export type AssetStatus = 'ready' | 'missing';

export interface EditorAsset extends MediaAssetRecord {
  status: AssetStatus;
  url: string | null;
  thumbnailUrl: string | null;
}

export interface EditorFileState {
  id: string;
  asset: EditorAsset;
  track: TimelineTrack;
  clips: TimelineClip[];
  renderProfile: RenderProfile;
  selectedClipIds: string[];
  playheadMs: number;
  zoom: number;
  previewVolume: number;
  previewMuted: boolean;
  isPlaying: boolean;
  markerRect: VideoMarkerRect | null;
}

export interface EditorWorkspaceState {
  workspaceName: string;
  activeFileId: string | null;
  files: EditorFileState[];
}

export const DEFAULT_WORKSPACE_NAME = 'Video Workspace';

export const DEFAULT_RENDER_PROFILE: RenderProfile = {
  format: 'mp4',
  fps: 60,
  videoQuality: '1080p',
  audioBitrateKbps: 320,
};

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
    id: createId('clip'),
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
  const track = options.track ? { ...options.track } : createSingleTrack();
  const clips = options.clips?.length
    ? options.clips.map((clip) => ({ ...clip }))
    : [createDefaultClip(asset.id, track.id, asset.durationMs)];

  return {
    id: options.id ?? createId('file'),
    asset,
    track,
    clips,
    renderProfile: {
      ...DEFAULT_RENDER_PROFILE,
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
  };
}

export function getActiveFile(state: EditorWorkspaceState) {
  if (!state.activeFileId) {
    return null;
  }

  return state.files.find((file) => file.id === state.activeFileId) ?? null;
}

export function findClipAtPlayhead(clips: TimelineClip[], playheadMs: number) {
  return clips.find((clip) => playheadMs >= clip.startMs && playheadMs < clipEndMs(clip)) ?? null;
}

export function getSourceTimeAtPlayhead(file: EditorFileState) {
  const clip = findClipAtPlayhead(file.clips, file.playheadMs);
  if (!clip) {
    return null;
  }

  return clamp(
    clip.inPointMs + (file.playheadMs - clip.startMs),
    0,
    file.asset.durationMs,
  );
}
