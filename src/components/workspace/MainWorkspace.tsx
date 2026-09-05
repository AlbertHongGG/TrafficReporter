import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle } from 'lucide-react';
import styles from './MainWorkspace.module.css';

import { EditorProvider } from './EditorContext';
import { Toolbar } from './toolbar/Toolbar';
import { MediaBinPanel } from './media-bin/MediaBinPanel';
import { VideoPlayerPanel } from './video-player/VideoPlayerPanel';
import { TransportRow } from './transport-row/TransportRow';
import { Timeline } from './timeline/Timeline';

import { useEditorPlayback } from './hooks/useEditorPlayback';
import { useMediaIngestion } from './hooks/useMediaIngestion';
import { useMarkerInteraction } from './hooks/useMarkerInteraction';
import { useWorkspaceHotkeys } from './hooks/useWorkspaceHotkeys';

import { useEditorSessionController } from '../../vnext/editor/application/useEditorSessionController';
import { useLprWorkflow } from '../../modules/editor/application/useLprWorkflow';
import { useAiEvidenceWorkflow } from '../../modules/editor/application/useAiEvidenceWorkflow';
import { useWindowCoordinator } from '../../modules/editor/application/useWindowCoordinator';
import { exportCurrentFrame } from '../../modules/editor/application/frameExportService';
import { getActiveFile, getTimelineDuration } from '../../modules/editor/domain/model';

export interface MediaEditorWorkspaceProps {
  isActive?: boolean;
}

export const MediaEditorWorkspace: React.FC<MediaEditorWorkspaceProps> = ({ isActive = true }) => {
  const { state, dispatch, sessionRevision } = useEditorSessionController();
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
    dispatch,
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
    dispatch,
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
    dispatch,
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
    dispatch,
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
    dispatch,
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
    dispatch,
    stopPlayback,
  });

  // Global Workspace Hotkeys
  useWorkspaceHotkeys({
    selectedClip,
    togglePlay,
    dispatch,
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
    <EditorProvider value={{ state, dispatch, activeFile: activeFile ?? undefined }}>
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
              dispatch={dispatch}
              seekTo={seekTo}
              stopPlayback={stopPlayback}
              onScrubStateChange={setIsScrubbing}
            />
          </main>
        </div>
      </div>
    </EditorProvider>
  );
};

export default MediaEditorWorkspace;
