import type { OutputCompressionModePayload, VideoMarkerRectPayload } from '../../../domain/ipc/bindings';

export type ExportFormat = 'mp4' | 'mkv';
export type VideoQuality = 'source' | '2160p' | '1440p' | '1080p' | '720p' | '480p';
export type AudioBitrateKbps = 320 | 256 | 192 | 128 | 96;
export type OutputCompressionMode = OutputCompressionModePayload;
export const DEFAULT_OUTPUT_COMPRESSION_MODE: OutputCompressionMode = 'standard';

// Lifted from the IPC single source (bindings payload is nullable over the wire;
// the frontend domain holds resolved values).
export type VideoMarkerRect = {
  [K in keyof VideoMarkerRectPayload]: NonNullable<VideoMarkerRectPayload[K]>;
};

export interface RenderProfile {
  format: ExportFormat;
  fps: number;
  videoQuality?: VideoQuality;
  audioBitrateKbps?: AudioBitrateKbps;
  compressionMode: OutputCompressionMode;
}

export type ExportSource = {
  id: string;
  name: string;
  path: string;
  hasVideo: boolean;
  hasAudio: boolean;
  width?: number;
  height?: number;
};

export interface ExportTrack {
  id: string;
  name: string;
  order: number;
}

export interface ExportClip {
  id: string;
  assetId: string;
  trackId: string;
  startMs: number;
  inPointMs: number;
  outPointMs: number;
  muted: boolean;
}

export interface ExportSnapshot {
  fileId: string;
  fileName: string;
  workspaceName: string;
  suggestedName: string;
  timelineDurationMs: number;
  hasVideo: boolean;
  hasAudio: boolean;
  dominantWidth?: number;
  dominantHeight?: number;
  sources: ExportSource[];
  tracks: ExportTrack[];
  clips: ExportClip[];
  renderProfile: RenderProfile;
}

export interface TimelineExportRequest {
  outputPath: string;
  profile: RenderProfile;
  snapshot: ExportSnapshot;
}

export interface FrameExportRequest {
  outputPath: string;
  sourcePath: string;
  timeMs: number;
  markerRect: VideoMarkerRect | null;
  compressionMode: OutputCompressionMode;
}

export interface ExportProgressPayload {
  progress: number;
  stage: string;
  detail: string;
  done: boolean;
  failed: boolean;
}
