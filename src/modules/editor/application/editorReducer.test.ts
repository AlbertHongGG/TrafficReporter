import { describe, expect, it } from 'vitest'

import { editorReducer } from './editorReducer'
import { getLprSessionByFileId } from '../domain/analysisState'
import { buildDefaultWorkspaceState, buildEditorFileState } from '../domain/model'
import type { EditorWorkspaceState } from '../domain/model'

function createWorkspaceState(): EditorWorkspaceState {
  const file = buildEditorFileState({
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

  return {
    ...buildDefaultWorkspaceState(),
    activeFileId: file.id,
    files: [file],
  }
}

describe('editorReducer LPR workflow', () => {
  it('selects the first target track and clones nested frame boxes', () => {
    const state = createWorkspaceState()
    const track = {
      id: 'track-1',
      className: 'motorcycle',
      label: 'motorcycle 1',
      confidence: 0.93,
      frames: [
        {
          id: 'frame-1',
          timeMs: 1200,
          box: { x: 0.1, y: 0.2, width: 0.25, height: 0.18 },
          confidence: 0.88,
          className: 'motorcycle',
        },
      ],
    }

    const nextState = editorReducer(state, {
      type: 'set-lpr-target-tracks',
      targetTracks: [track],
    })
    const lprState = getLprSessionByFileId(nextState.analysis, nextState.activeFileId)

    track.frames[0].box.x = 0.75

    expect(lprState.selectedTargetTrackId).toBe('track-1')
    expect(lprState.targetTracks[0]?.frames[0]?.box.x).toBe(0.1)
  })

  it('clears transient LPR results while keeping interval and history evidence', () => {
    const candidate = {
      id: 'candidate-1',
      text: 'ABC1234',
      confidence: 0.97,
      source: 'fused' as const,
      frameTimeMs: 1500,
      countryCode: 'TW',
      box: { x: 0.2, y: 0.3, width: 0.18, height: 0.09 },
      quality: null,
    }

    let state = createWorkspaceState()
    state = editorReducer(state, {
      type: 'set-lpr-interval',
      interval: { startMs: 1000, endMs: 2400 },
    })
    state = editorReducer(state, {
      type: 'set-lpr-candidates',
      candidates: [candidate],
    })
    state = editorReducer(state, {
      type: 'append-lpr-history',
      entry: {
        id: 'history-1',
        createdAt: '2026-05-07T00:00:00.000Z',
        interval: { startMs: 1000, endMs: 2400 },
        targetTrackId: null,
        acceptedCandidateId: candidate.id,
        analysisProfileId: 'balanced',
        developerDiagnosticsEnabled: false,
        candidates: [candidate],
        summary: 'Best candidate ABC1234',
      },
    })

    const nextState = editorReducer(state, { type: 'clear-lpr-results' })
    const lprState = getLprSessionByFileId(nextState.analysis, nextState.activeFileId)

    expect(lprState.candidates).toEqual([])
    expect(lprState.samples).toEqual([])
    expect(lprState.targetTracks).toEqual([])
    expect(lprState.interval).toEqual({ startMs: 1000, endMs: 2400 })
    expect(lprState.history).toHaveLength(1)
    expect(lprState.history[0]?.summary).toBe('Best candidate ABC1234')
  })
})