import React from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, MonitorPlay, Music, Video as VideoIcon, CheckCircle2, AlertCircle, FolderOpen, ChevronRight } from 'lucide-react'

import { Select } from '../../../components/Select/Select'
import {
  AUDIO_FORMATS,
  AUDIO_QUALITIES,
  VIDEO_FORMATS,
  VIDEO_QUALITIES,
  useYoutubeDownloader,
} from '../application/useYoutubeDownloader'
import styles from './YoutubeDownloader.module.css'

interface YoutubeDownloaderProps {
  isActive?: boolean
}

export const YoutubeDownloader: React.FC<YoutubeDownloaderProps> = () => {
  const {
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
    hasSearched,
  } = useYoutubeDownloader()

  const formatDuration = (seconds: number) => {
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ ease: 'easeOut', duration: 0.2 }}
      className={styles.container}
    >
      <motion.div layout className={styles.searchSection} transition={{ duration: 0.3, ease: 'easeInOut' }}>
        <AnimatePresence mode="popLayout">
          {!hasSearched && (
            <motion.div
              layout
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, filter: 'blur(4px)', y: -20 }}
              transition={{ duration: 0.3 }}
              className={styles.heroHeader}
            >
              <div className={styles.heroIconWrapper}>
                <MonitorPlay className={styles.heroIcon} size={42} strokeWidth={1.5} />
                <div className={styles.heroIconGlow} />
              </div>
              <h1 className={styles.heroTitle}>Media Downloader</h1>
            </motion.div>
          )}
        </AnimatePresence>

        <motion.div layout className={styles.inputWrapper}>
          <Search className={styles.inputIcon} size={18} />
          <input
            type="text"
            placeholder="Paste YouTube URL and press Enter..."
            value={url}
            onChange={(event) => {
              setUrl(event.target.value)
            }}
            onKeyDown={(event) => event.key === 'Enter' && void analyze()}
            className={styles.input}
            spellCheck={false}
          />
          {isAnalyzing && (
            <motion.div className={styles.spinner} animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1, ease: 'linear' }} />
          )}
          {!isAnalyzing && url && !hasSearched && (
            <button className={styles.analyzeBtn} onClick={() => void analyze()}>
              <ChevronRight size={18} />
            </button>
          )}
        </motion.div>
      </motion.div>

      <AnimatePresence mode="wait">
        {error && (
          <motion.div
            key="error"
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className={styles.errorAlert}
          >
            <AlertCircle size={16} />
            {error}
          </motion.div>
        )}

        {info && !isAnalyzing && (
          <motion.div
            key="result"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 10 }}
            transition={{ ease: 'easeOut', duration: 0.3 }}
            className={styles.resultSection}
          >
            <div className={styles.previewCard}>
              <div className={styles.previewImage}>
                <img src={info.thumbnail} alt="Thumbnail" />
                <span className={styles.duration}>{formatDuration(info.duration)}</span>
              </div>

              <div className={styles.previewInfo}>
                <h3 className={styles.videoTitle} title={info.title}>{info.title}</h3>

                <div className={styles.segmentedControl}>
                  <button
                    className={`${styles.segmentBtn} ${mode === 'video' ? styles.active : ''}`}
                    onClick={() => {
                      setMode('video')
                    }}
                  >
                    <VideoIcon size={14} /> Video
                  </button>
                  <button
                    className={`${styles.segmentBtn} ${mode === 'audio' ? styles.active : ''}`}
                    onClick={() => {
                      setMode('audio')
                    }}
                  >
                    <Music size={14} /> Audio
                  </button>
                </div>

                <div className={styles.settingsGrid}>
                  <div className={styles.settingGroup}>
                    <span className={styles.settingLabel}>Format</span>
                    <Select
                      value={format}
                      onChange={(value) => setFormat(value)}
                      options={(mode === 'video' ? VIDEO_FORMATS : AUDIO_FORMATS).map((entry) => ({
                        label: entry.toUpperCase(),
                        value: entry,
                      }))}
                    />
                  </div>

                  <div className={styles.settingGroup}>
                    <span className={styles.settingLabel}>Quality</span>
                    <Select
                      value={quality}
                      onChange={(value) => setQuality(value)}
                      options={(mode === 'video' ? VIDEO_QUALITIES : AUDIO_QUALITIES).map((entry) => ({
                        label: entry,
                        value: entry,
                      }))}
                    />
                  </div>
                </div>

                <div className={styles.actionSection}>
                  <div className={styles.actionState}>
                    {isDownloading ? (
                      <div className={styles.progressContainer}>
                        <div className={styles.progressHeader}>
                          <span className={styles.progressLabel}>{statusText}</span>
                          <span className={styles.progressPercent}>{progress}%</span>
                        </div>
                        <div className={styles.progressBar}>
                          <motion.div
                            className={styles.progressFill}
                            initial={{ width: 0 }}
                            animate={{ width: `${progress}%` }}
                            transition={{ ease: 'linear', duration: 0.2 }}
                          />
                        </div>
                      </div>
                    ) : downloadDone ? (
                      <div className={styles.successMessage}>
                        <CheckCircle2 size={16} />
                        Download Complete
                      </div>
                    ) : (
                      <button
                        className={styles.downloadBtn}
                        onClick={() => void download()}
                      >
                        <FolderOpen size={16} />
                        Download
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
