import type { OutputCompressionModePayload, VideoMarkerRectPayload } from '../../../platform/ipc/bindings';
import type { WorkspaceRuntimeSnapshot } from '../../../platform/transport/types';
import type { LiveTransportSnapshot } from '../../editor/application/liveTransport';

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

/**
 * Phase 5-D 絞殺：快照型別收斂到 WorkspaceRuntimeSnapshot 交叉 export 自身欄位。
 * 共用欄位（workspaceName / activeFileName / hasActiveFile / runtimeStatus /
 * playheadMs）由基底提供；其餘為 export 自身欄位。
 * exportContract.liveEvent 為 `editor/export-progress`（Rust 進度推送通道），
 * 主視窗 builder 不攜帶 live 疊加，故 liveTransport 收斂為可選（缺席視為無）。
 */
export type ExportSnapshot = Omit<WorkspaceRuntimeSnapshot, 'liveTransport'> & {
  liveTransport?: LiveTransportSnapshot | null;
  fileId: string;
  fileName: string;
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
};

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
