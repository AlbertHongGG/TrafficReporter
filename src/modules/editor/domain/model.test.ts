import { describe, expect, it } from 'vitest'

import {
  DEFAULT_RENDER_PROFILE,
  DEFAULT_ZOOM,
  buildDefaultWorkspaceState,
  buildEditorFileState,
  createRunFolderId,
  findClosestTrackFrame,
} from './model'
import { buildLprTargetAnchor, resolveLprAnalysisTargetVehicleKind } from './lprState'

describe('editor model', () => {
  it('starts a new workspace with no active file and no imported media', () => {
    const state = buildDefaultWorkspaceState()

    expect(state).toEqual({
      workspaceName: 'Video Workspace',
      activeFileId: null,
      files: [],
      analysis: {
        aiEvidenceSessionsByFileId: {},
        lprRuntimeStatus: null,
        lprSessionsByFileId: {},
      },
    })
  })

  it('creates a per-file workspace with one track and one default clip', () => {
    const fileState = buildEditorFileState({
      id: 'asset-1',
      name: 'camera-a.mp4',
      path: 'C:/media/camera-a.mp4',
      kind: 'video',
      durationMs: 8000,
      hasVideo: true,
      hasAudio: true,
      fps: 30,
      width: 1920,
      height: 1080,
      status: 'ready',
      url: 'asset://camera-a.mp4',
      thumbnailUrl: null,
    })

    expect(fileState.track).toMatchObject({ name: 'Track 1', order: 1 })
    expect(fileState.clips).toHaveLength(1)
    expect(fileState.clips[0]).toMatchObject({
      assetId: 'asset-1',
      trackId: fileState.track.id,
      startMs: 0,
      inPointMs: 0,
      outPointMs: 8000,
      muted: false,
    })
    expect(fileState.renderProfile).toEqual({
      ...DEFAULT_RENDER_PROFILE,
      fps: 30,
    })
    expect(fileState.zoom).toBe(DEFAULT_ZOOM)
    expect(fileState.markerRect).toBeNull()
  })

  it('finds the closest tracked frame with binary-search semantics', () => {
    const track = {
      frames: [
        { id: 'f1', timeMs: 100, box: { x: 0, y: 0, width: 0.1, height: 0.1 }, confidence: 0.9, className: 'car' },
        { id: 'f2', timeMs: 260, box: { x: 0, y: 0, width: 0.1, height: 0.1 }, confidence: 0.9, className: 'car' },
        { id: 'f3', timeMs: 410, box: { x: 0, y: 0, width: 0.1, height: 0.1 }, confidence: 0.9, className: 'car' },
      ],
    }

    expect(findClosestTrackFrame(track, 260)?.id).toBe('f2')
    expect(findClosestTrackFrame(track, 280)?.id).toBe('f2')
    expect(findClosestTrackFrame(track, 800, 100)).toBeNull()
  })

  it('creates run folder ids in the shared local-time format', () => {
    expect(createRunFolderId()).toMatch(/^\d{6}-\d{6}-[0-9a-f]{8}$/)
  })

  it('narrows analysis vehicle kind to the selected target class', () => {
    expect(resolveLprAnalysisTargetVehicleKind({ className: 'motorcycle' }, 'vehicle')).toBe('motorcycle')
    expect(resolveLprAnalysisTargetVehicleKind({ className: 'car' }, 'vehicle')).toBe('car')
    expect(resolveLprAnalysisTargetVehicleKind({ className: 'vehicle' }, 'vehicle')).toBe('vehicle')
    expect(resolveLprAnalysisTargetVehicleKind(null, 'truck')).toBe('truck')
  })

  it('builds a target anchor from the frame nearest the requested selection time', () => {
    const anchor = buildLprTargetAnchor({
      id: 'track-1',
      className: 'motorcycle',
      frames: [
        { id: 'f1', timeMs: 6210, box: { x: 0.18, y: 0.34, width: 0.14, height: 0.22 }, confidence: 0.9, className: 'motorcycle' },
        { id: 'f2', timeMs: 7030, box: { x: 0.44, y: 0.32, width: 0.12, height: 0.24 }, confidence: 0.91, className: 'motorcycle' },
      ],
    }, 6280)

    expect(anchor).toEqual({
      trackId: 'track-1',
      className: 'motorcycle',
      timeMs: 6210,
      box: { x: 0.18, y: 0.34, width: 0.14, height: 0.22 },
    })
  })
})