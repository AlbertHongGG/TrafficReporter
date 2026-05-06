import { describe, expect, it } from 'vitest'

import { buildEditorFileState, clipDurationMs } from './model'
import { deleteSelectedClips, setSelectedClipMuted, splitClipAt } from './timelineCommands'

describe('timeline commands', () => {
  function createFileState() {
    return buildEditorFileState({
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
  }

  it('mutes every selected clip without mutating the previous state', () => {
    const fileState = createFileState()
    fileState.selectedClipIds = [fileState.clips[0].id]

    const nextState = setSelectedClipMuted(fileState, true)

    expect(nextState.clips[0]?.muted).toBe(true)
    expect(fileState.clips[0]?.muted).toBe(false)
  })

  it('splits a clip into two segments and selects the new right segment', () => {
    const fileState = createFileState()
    const clip = fileState.clips[0]

    const nextState = splitClipAt(fileState, clip.id, 3000)

    expect(nextState.clips).toHaveLength(2)
    expect(clipDurationMs(nextState.clips[0])).toBe(3000)
    expect(nextState.clips[1]).toMatchObject({
      startMs: 3000,
      inPointMs: 3000,
      outPointMs: 8000,
    })
    expect(nextState.selectedClipIds).toEqual([nextState.clips[1].id])
  })

  it('deletes every selected clip from the active file state', () => {
    const fileState = createFileState()
    fileState.selectedClipIds = [fileState.clips[0].id]

    const nextState = deleteSelectedClips(fileState)

    expect(nextState.clips).toHaveLength(0)
    expect(nextState.selectedClipIds).toEqual([])
  })
})