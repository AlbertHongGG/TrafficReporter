import type {
  OutputCompressionMode,
  RenderProfile,
  TimelineClip,
  TimelineTrack,
  VideoMarkerRect,
} from './editor';

export type { AudioBitrateKbps, ExportFormat, OutputCompressionMode, RenderProfile, VideoQuality } from './editor';

export interface ExportSource {
  id: string;
  name: string;
  path: string;
  hasVideo: boolean;
  hasAudio: boolean;
  width?: number;
  height?: number;
}

export type ExportTrack = Pick<TimelineTrack, 'id' | 'name' | 'order'>;

export type ExportClip = Pick<
  TimelineClip,
  'id' | 'assetId' | 'trackId' | 'startMs' | 'inPointMs' | 'outPointMs' | 'muted'
>;

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