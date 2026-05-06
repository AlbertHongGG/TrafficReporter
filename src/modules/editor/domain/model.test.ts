import { describe, expect, it } from 'vitest'

import {
  DEFAULT_RENDER_PROFILE,
  DEFAULT_ZOOM,
  buildDefaultWorkspaceState,
  buildEditorFileState,
} from './model'

describe('editor model', () => {
  it('starts a new workspace with no active file and no imported media', () => {
    const state = buildDefaultWorkspaceState()

    expect(state).toEqual({
      workspaceName: 'Video Workspace',
      activeFileId: null,
      files: [],
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
    expect(fileState.renderProfile).toEqual(DEFAULT_RENDER_PROFILE)
    expect(fileState.zoom).toBe(DEFAULT_ZOOM)
    expect(fileState.markerRect).toBeNull()
  })
})