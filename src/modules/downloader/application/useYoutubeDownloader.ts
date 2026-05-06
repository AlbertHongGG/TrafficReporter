import React from 'react'
import type { UnlistenFn } from '@tauri-apps/api/event'
import { open } from '@tauri-apps/plugin-dialog'

import type { VideoInfo } from '../../../shared/contracts/downloader'
import { createLogger } from '../../../utils/logger'
import {
  downloadYoutube,
  getYoutubeInfo,
  listenDownloadProgress,
} from '../infrastructure/downloaderApi'

const log = createLogger('YoutubeDownloader')
const DOWNLOAD_SUCCESS_RESET_DELAY_MS = 2600

export type DownloadMode = 'video' | 'audio'

export const VIDEO_FORMATS = ['mp4', 'mkv', 'webm']
export const AUDIO_FORMATS = ['mp3', 'm4a', 'wav', 'flac']
export const VIDEO_QUALITIES = ['2160p (4K)', '1440p (2K)', '1080p', '720p', '480p', '360p']
export const AUDIO_QUALITIES = ['320kbps', '256kbps', '192kbps', '128kbps', '64kbps']

function defaultFormatForMode(mode: DownloadMode) {
  return mode === 'video' ? 'mp4' : 'mp3'
}

function defaultQualityForMode(mode: DownloadMode) {
  return mode === 'video' ? '1080p' : '320kbps'
}

function toErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message
  }

  return String(error)
}

export function useYoutubeDownloader() {
  const [url, setUrlState] = React.useState('')
  const [isAnalyzing, setIsAnalyzing] = React.useState(false)
  const [info, setInfo] = React.useState<VideoInfo | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [mode, setModeState] = React.useState<DownloadMode>('video')
  const [format, setFormat] = React.useState(defaultFormatForMode('video'))
  const [quality, setQuality] = React.useState(defaultQualityForMode('video'))
  const [isDownloading, setIsDownloading] = React.useState(false)
  const [progress, setProgress] = React.useState(0)
  const [statusText, setStatusText] = React.useState('')
  const [downloadDone, setDownloadDone] = React.useState(false)
  const unlistenRef = React.useRef<UnlistenFn | null>(null)
  const successResetTimeoutRef = React.useRef<number | null>(null)

  const clearSuccessResetTimeout = React.useCallback(() => {
    if (successResetTimeoutRef.current !== null) {
      window.clearTimeout(successResetTimeoutRef.current)
      successResetTimeoutRef.current = null
    }
  }, [])

  React.useEffect(() => {
    return () => {
      clearSuccessResetTimeout()
      void unlistenRef.current?.()
    }
  }, [clearSuccessResetTimeout])

  React.useEffect(() => {
    if (!downloadDone) {
      clearSuccessResetTimeout()
      return undefined
    }

    successResetTimeoutRef.current = window.setTimeout(() => {
      setDownloadDone(false)
      setProgress(0)
      setStatusText('')
      successResetTimeoutRef.current = null
    }, DOWNLOAD_SUCCESS_RESET_DELAY_MS)

    return () => {
      clearSuccessResetTimeout()
    }
  }, [clearSuccessResetTimeout, downloadDone])

  const resetSearchResult = React.useCallback(() => {
    setInfo(null)
    setError(null)
    setDownloadDone(false)
  }, [])

  const setUrl = React.useCallback((nextUrl: string) => {
    setUrlState(nextUrl)
    clearSuccessResetTimeout()
    setInfo((currentInfo) => {
      if (currentInfo && nextUrl !== url) {
        setError(null)
        setDownloadDone(false)
        setProgress(0)
        setStatusText('')
        return null
      }

      return currentInfo
    })
  }, [clearSuccessResetTimeout, url])

  const setMode = React.useCallback((nextMode: DownloadMode) => {
    clearSuccessResetTimeout()
    setModeState(nextMode)
    setFormat(defaultFormatForMode(nextMode))
    setQuality(defaultQualityForMode(nextMode))
    setDownloadDone(false)
    setProgress(0)
    setStatusText('')
  }, [clearSuccessResetTimeout])

  const analyze = React.useCallback(async () => {
    if (!url.trim()) {
      return
    }

    setIsAnalyzing(true)
    setError(null)
    clearSuccessResetTimeout()
    setDownloadDone(false)
    log.info('Analyzing URL.', { url })

    try {
      const nextInfo = await getYoutubeInfo(url)
      setInfo(nextInfo)
      setFormat(defaultFormatForMode(mode))
      setQuality(defaultQualityForMode(mode))
    } catch (error) {
      const message = toErrorMessage(error)
      log.error('Failed to analyze URL.', message)
      setError(message)
    } finally {
      setIsAnalyzing(false)
    }
  }, [clearSuccessResetTimeout, mode, url])

  const download = React.useCallback(async () => {
    const selectedDir = await open({
      directory: true,
      multiple: false,
      title: 'Choose download location',
    })

    if (!selectedDir) {
      return
    }

    const saveDir = selectedDir as string
    clearSuccessResetTimeout()
    setIsDownloading(true)
    setProgress(0)
    setStatusText('Preparing download...')
    setDownloadDone(false)
    setError(null)

    if (unlistenRef.current) {
      await unlistenRef.current()
    }

    unlistenRef.current = await listenDownloadProgress((payload) => {
      setProgress(Math.round(payload.percent))
      if (payload.statusText) {
        setStatusText(payload.statusText)
      }
    })

    try {
      await downloadYoutube({ url, format, quality, saveDir })
      setProgress(100)
      setStatusText('Complete')
      setDownloadDone(true)
    } catch (error) {
      const message = toErrorMessage(error)
      log.error('Download failed.', message)
      setError(message)
      setProgress(0)
      setStatusText('')
    } finally {
      setIsDownloading(false)
      if (unlistenRef.current) {
        await unlistenRef.current()
        unlistenRef.current = null
      }
    }
  }, [clearSuccessResetTimeout, format, quality, url])

  return {
    url,
    setUrl,
    isAnalyzing,
    info,
    error,
    mode,
    setMode,
    format,
    setFormat,
    quality,
    setQuality,
    isDownloading,
    progress,
    statusText,
    downloadDone,
    analyze,
    download,
    hasSearched: info !== null || isAnalyzing || error !== null,
    resetSearchResult,
  }
}