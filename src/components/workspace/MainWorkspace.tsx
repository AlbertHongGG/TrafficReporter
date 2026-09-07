import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle } from 'lucide-react';
import styles from './MainWorkspace.module.css';

import { useEditorStore } from '../../modules/editor/application/store/store';
import { useEditorSessionSync } from '../../modules/editor/application/editorSessionSync';
import { Toolbar } from './Toolbar';
import { MediaBinPanel } from './MediaBinPanel';
import { VideoPlayerPanel } from './video-player/VideoPlayerPanel';
import { TransportRow } from './TransportRow';
import { Timeline } from './Timeline';

import { useEditorPlayback } from '../../modules/editor/application/useEditorPlayback';
import { useMediaIngestion } from '../../modules/editor/application/useMediaIngestion';
import { useMarkerInteraction } from '../../modules/editor/application/useMarkerInteraction';
import { useWorkspaceHotkeys } from '../../modules/editor/application/useWorkspaceHotkeys';

import { useLprWorkflow } from '../../modules/editor/application/useLprWorkflow';
import { useAiEvidenceWorkflow } from '../../modules/editor/application/useAiEvidenceWorkflow';
import { useWindowCoordinator } from '../../modules/editor/application/useWindowCoordinator';
import { exportCurrentFrame } from '../../modules/editor/application/frameExportService';
import { getActiveFile, getTimelineDuration } from '../../modules/editor/domain/model';

export interface MediaEditorWorkspaceProps {
  isActive?: boolean;
}

export const MediaEditorWorkspace: React.FC<MediaEditorWorkspaceProps> = ({ isActive = true }) => {
  useEditorSessionSync();
  const state = useEditorStore((s) => s.workspace);
  const sessionRevision = useEditorStore((s) => s.revision);
  const [workspaceFeedback, setWorkspaceFeedback] = useState<string | null>(null);
  const [isScrubbing, setIsScrubbing] = useState(false);
  const plateWindowLiveSyncEnabledRef = useRef(false);

  const activeFile = useMemo(() => getActiveFile(state), [state]);
  const activeClips = useMemo(() => activeFile?.clips ?? [], [activeFile]);
  const selectedClipId = activeFile?.selectedClipIds[0] ?? null;
  const selectedClip = useMemo(
    () => activeClips.find((clip) => clip.id === selectedClipId) ?? null,
    [activeClips, selectedClipId],
  );
  const timelineDurationMs = useMemo(() => getTimelineDuration(activeClips), [activeClips]);

  const missingFiles = useMemo(
    () => state.files.filter((f) => f.asset.status === 'missing'),
    [state.files],
  );

  // Playback & Viewport Controller
  const {
    previewContainerRef,
    previewVideoRef,
    currentTimecodeRef,
    livePlayheadMsRef,
    liveTransportStore,
    previewState,
    previewViewport,
    currentPlayheadMs,
    currentIsPlaying,
    togglePlay,
    seekTo,
    seekBy,
    stopPlayback,
  } = useEditorPlayback({
    activeFile,
    activeClips,
    timelineDurationMs,
    isScrubbing,
    isActive,
    plateWindowLiveSyncEnabledRef,
  });

  // LPR Domain & Application Workflow
  const {
    lprRuntimeStatus,
    lprState,
    lprAnalysisTrack,
    lprTopCandidate,
    lprSelectedTargetAnchor,
    canAnalyzeRange,
    latestCountryHintDraftRef,
    refreshLprRuntimeStatus,
    handleCancelLprJob,
    applyCountryHints,
    handleSetIntervalBoundary,
    handleUseClipInterval,
    handleScanLprTargets,
    handleAnalyzeLprFrame,
    handleAnalyzeLprInterval,
    handleSelectTargetTrack,
    handleExportLprEvidence,
    lprAnalysisVehicleKind,
  } = useLprWorkflow({
    state,
    activeFile,
    livePlayheadMsRef,
    currentIsPlaying,
    setWorkspaceFeedback,
  });

  // AI Evidence Workflow
  const {
    aiState,
    handleCancelAiJob,
    handleRunAiEvidence,
  } = useAiEvidenceWorkflow({
    state,
    activeFile,
    lprState,
    lprAnalysisVehicleKind,
    refreshLprRuntimeStatus,
    setWorkspaceFeedback,
  });

  // Multi-Window IPC Coordinator
  const {
    handleOpenPlateWindow,
    handleOpenAiPanelWindow,
    handleOpenExportWindow,
    handleToggleCompactExports,
  } = useWindowCoordinator({
    state,
    sessionRevision,
    activeFile,
    currentPlayheadMs,
    currentIsPlaying,
    lprRuntimeStatus,
    lprState,
    lprTopCandidate,
    lprSelectedTargetAnchor,
    canAnalyzeRange,
    latestCountryHintDraftRef,
    refreshLprRuntimeStatus,
    handleCancelLprJob,
    handleUseClipInterval,
    handleSetIntervalBoundary,
    applyCountryHints,
    handleScanLprTargets,
    handleAnalyzeLprFrame,
    handleAnalyzeLprInterval,
    handleExportLprEvidence,
    handleSelectTargetTrack,
    aiState,
    handleRunAiEvidence,
    handleCancelAiJob,
    setWorkspaceFeedback,
    plateWindowLiveSyncEnabledRef,
  });

  // Marker Interaction Overlay
  const {
    markerStyle,
    handleMarkerPointerDown,
    handleMarkerResizePointerDown,
    handleCreateMarker,
  } = useMarkerInteraction({
    activeFile,
    previewViewport,
  });

  // Media Ingestion & Bin Operations
  const {
    isExternalDropActive,
    importFeedback,
    handleImportClick,
    handleRelinkFile,
    handleSelectFile,
    handleRemoveFile,
  } = useMediaIngestion({
    stopPlayback,
  });

  // Global Workspace Hotkeys
  useWorkspaceHotkeys({
    selectedClip,
    togglePlay,
    livePlayheadMsRef,
  });

  // Frame Export
  const handleExportCurrentFrame = useCallback(async () => {
    await exportCurrentFrame({
      activeFile,
      playheadMs: livePlayheadMsRef.current,
      previewVideoElement: previewVideoRef.current,
      setFeedback: setWorkspaceFeedback,
      stopPlayback,
    });
  }, [activeFile, livePlayheadMsRef, previewVideoRef, stopPlayback]);

  // Synchronize runtime status on mount
  useEffect(() => {
    void refreshLprRuntimeStatus();
  }, [refreshLprRuntimeStatus]);

  return (
    <div className={styles.editor}>
        <Toolbar
          activeFile={activeFile ?? null}
          onExportCurrentFrame={handleExportCurrentFrame}
          onOpenExportWindow={handleOpenExportWindow}
          onOpenPlateWindow={handleOpenPlateWindow}
          onOpenAiPanelWindow={handleOpenAiPanelWindow}
          onToggleCompactExports={handleToggleCompactExports}
          onImportClick={handleImportClick}
        />

        {(workspaceFeedback || importFeedback) && (
          <section className={styles.noticeBar}>
            {workspaceFeedback && (
              <div className={`${styles.notice} ${styles.noticeError}`}>
                <AlertCircle size={15} />
                <span>{workspaceFeedback}</span>
              </div>
            )}
            {importFeedback && (
              <div className={`${styles.notice} ${styles.noticeError}`}>
                <AlertCircle size={15} />
                <span>{importFeedback}</span>
              </div>
            )}
          </section>
        )}

        <div className={styles.content}>
          <MediaBinPanel
            isExternalDropActive={isExternalDropActive}
            missingFiles={missingFiles}
            handleImportClick={handleImportClick}
            handleSelectFile={handleSelectFile}
            handleRelinkFile={handleRelinkFile}
            handleRemoveFile={handleRemoveFile}
          />

          <main className={styles.mainPanel}>
            <VideoPlayerPanel
              previewContainerRef={previewContainerRef}
              previewVideoRef={previewVideoRef}
              previewState={previewState}
              previewViewport={previewViewport}
              lprState={lprState}
              lprAnalysisTrack={lprAnalysisTrack}
              liveTransportStore={liveTransportStore}
              handleSelectTargetTrack={handleSelectTargetTrack}
              markerStyle={markerStyle}
              handleMarkerPointerDown={handleMarkerPointerDown}
              handleMarkerResizePointerDown={handleMarkerResizePointerDown}
              handleCreateMarker={handleCreateMarker}
            />

            <TransportRow
              currentTimecodeRef={currentTimecodeRef}
              displayPlayheadMs={currentPlayheadMs}
              livePlayheadMsRef={livePlayheadMsRef}
              seekBy={seekBy}
              togglePlay={togglePlay}
            />

            <Timeline
              activeFile={activeFile ?? null}
              activeClips={activeClips}
              timelineDurationMs={timelineDurationMs}
              liveTransportStore={liveTransportStore}
              seekTo={seekTo}
              stopPlayback={stopPlayback}
              onScrubStateChange={setIsScrubbing}
            />
          </main>
        </div>
      </div>
  );
};

export default MediaEditorWorkspace;
