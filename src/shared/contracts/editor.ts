export type MediaKind = 'video';

export interface MediaProbeResult {
  durationMs: number;
  hasVideo: boolean;
  hasAudio: boolean;
  fps?: number;
  width?: number;
  height?: number;
}

export interface MediaAssetRecord extends MediaProbeResult {
  id: string;
  name: string;
  path: string;
  kind: MediaKind;
}

export interface TimelineTrack {
  id: string;
  name: string;
  order: number;
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

export type ExportFormat = 'mp4' | 'mkv';

export type VideoQuality = 'source' | '2160p' | '1440p' | '1080p' | '720p' | '480p';

export type AudioBitrateKbps = 320 | 256 | 192 | 128 | 96;

export type OutputCompressionMode = 'standard' | 'compact';

export const DEFAULT_OUTPUT_COMPRESSION_MODE: OutputCompressionMode = 'standard';

export interface RenderProfile {
  format: ExportFormat;
  fps: number;
  videoQuality?: VideoQuality;
  audioBitrateKbps?: AudioBitrateKbps;
  compressionMode: OutputCompressionMode;
}

export interface VideoMarkerRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export type OperationFeedbackScope = 'import' | 'workspace' | 'export' | 'playback';

export interface OperationFeedback {
  scope: OperationFeedbackScope;
  message: string;
}