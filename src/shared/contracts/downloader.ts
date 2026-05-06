export interface VideoInfo {
  title: string;
  thumbnail: string;
  duration: number;
}

export interface DownloadProgressPayload {
  percent: number;
  status: string;
  statusText: string;
  phase: string;
}