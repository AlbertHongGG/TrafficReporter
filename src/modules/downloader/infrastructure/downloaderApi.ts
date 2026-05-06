import { invoke } from '@tauri-apps/api/core'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'

import type { DownloadProgressPayload, VideoInfo } from '../../../shared/contracts/downloader'

interface DownloadProgressEventPayload {
  percent: number
  status: string
  status_text: string
  phase: string
}

export function getYoutubeInfo(url: string) {
  return invoke<VideoInfo>('get_youtube_info', { url })
}

export function downloadYoutube(request: {
  url: string
  format: string
  quality: string
  saveDir: string
}) {
  return invoke<void>('download_youtube', request)
}

export function listenDownloadProgress(
  listener: (payload: DownloadProgressPayload) => void,
) {
  return listen<DownloadProgressEventPayload>('download-progress', (event) => {
    listener({
      percent: event.payload.percent,
      status: event.payload.status,
      statusText: event.payload.status_text,
      phase: event.payload.phase,
    })
  }) as Promise<UnlistenFn>
}