/**
 * Infrastructure boundary-validation contract (Blueprint §2.3, Phase 2-B).
 *
 * Locks the behavior of `mediaSchemas.ts` (editor media probing, frame
 * export, AI-panel `saveGeneratedMediaAsset`) and `exportSchemas.ts`
 * (timeline-export wire shapes + acknowledgement): every cross-process
 * response must pass its zod schema after `unwrapCommand` and before any
 * mapper/domain code. Valid payloads (including wire-nullable fields) are
 * accepted as clean objects; malformed payloads throw a structured
 * `IpcCommandError` naming the command plus a zod issue summary.
 *
 * Contract-tightening note: malformed cross-process input previously flowed
 * into the callers as undefined behavior (whatever the backend happened to
 * send). It now fails loudly with `IpcCommandError`, which is the intended
 * Phase 2 contract — not a behavior regression. Public API signatures and
 * success-path behavior are unchanged.
 */
import { describe, expect, it } from 'vitest';

import type {
  MediaProbePayload,
  TimelineExportRequest,
} from '../../../domain/ipc/bindings';
import { IpcCommandError } from '../../../infrastructure/ipc-unwrap';
import { parseTimelineExportResponse, timelineExportRequestSchema } from '../../export/infrastructure/exportSchemas';
import {
  parseFrameExportResponse,
  parseMediaProbeResponse,
  parseSaveGeneratedMediaAssetResponse,
} from './mediaSchemas';

function expectCommandError(fn: () => unknown, command: string): void {
  try {
    fn();
  } catch (error: unknown) {
    expect(error).toBeInstanceOf(IpcCommandError);
    const failure = error as IpcCommandError;
    expect(failure.command).toBe(command);
    expect(failure.message).toContain(command);
    return;
  }
  throw new Error(`expected IpcCommandError for ${command}`);
}

describe('media probe boundary schema', () => {
  it('accepts a valid probe payload with wire-nullable fields', () => {
    const raw: MediaProbePayload = {
      durationMs: 8000,
      hasVideo: true,
      hasAudio: false,
      fps: 30,
      audioBitrateKbps: null,
      width: 1920,
      height: null,
    };
    expect(parseMediaProbeResponse('probe_media_source', raw)).toEqual(raw);
  });

  it('rejects a probe payload with a wrong-typed field', () => {
    const raw = {
      durationMs: 'eight seconds',
      hasVideo: true,
      hasAudio: false,
      fps: 30,
      audioBitrateKbps: null,
      width: 1920,
      height: 1080,
    };
    expectCommandError(() => parseMediaProbeResponse('probe_media_source', raw), 'probe_media_source');
  });

  it('rejects a probe payload missing a required field', () => {
    const { hasVideo: _omitted, ...withoutHasVideo } = {
      durationMs: 8000,
      hasVideo: true,
      hasAudio: true,
      fps: null,
      audioBitrateKbps: null,
      width: null,
      height: null,
    };
    expect(_omitted).toBe(true);
    expectCommandError(
      () => parseMediaProbeResponse('probe_media_source', withoutHasVideo),
      'probe_media_source',
    );
  });
});

describe('frame export / generated-asset acknowledgement schemas', () => {
  it('accepts the null frame-export acknowledgement and rejects a non-null one', () => {
    expect(parseFrameExportResponse('export_frame_image', null)).toBeNull();
    expectCommandError(
      () => parseFrameExportResponse('export_frame_image', { ok: true }),
      'export_frame_image',
    );
  });

  it('accepts the null save-asset acknowledgement and rejects a non-null one', () => {
    expect(parseSaveGeneratedMediaAssetResponse('save_generated_media_asset', null)).toBeNull();
    expectCommandError(
      () => parseSaveGeneratedMediaAssetResponse('save_generated_media_asset', 'done'),
      'save_generated_media_asset',
    );
  });
});

describe('export boundary schemas', () => {
  it('accepts a valid timeline-export wire shape', () => {
    const raw: TimelineExportRequest = {
      outputPath: 'C:/exports/cut.mp4',
      profile: {
        format: 'mp4',
        fps: 30,
        videoQuality: '1080p',
        audioBitrateKbps: null,
        compressionMode: 'standard',
      },
      snapshot: {
        fileId: 'file-1',
        fileName: 'camera-a.mp4',
        workspaceName: 'Interview Cut',
        suggestedName: 'cut',
        timelineDurationMs: 3500,
        hasVideo: true,
        hasAudio: true,
        dominantWidth: null,
        dominantHeight: null,
        sources: [],
        tracks: [],
        clips: [],
        renderProfile: {
          format: 'mp4',
          fps: 30,
          videoQuality: null,
          audioBitrateKbps: null,
          compressionMode: 'compact',
        },
      },
    };
    expect(timelineExportRequestSchema.safeParse(raw).success).toBe(true);
  });

  it('rejects an export wire shape with a mistyped nested profile', () => {
    const raw = {
      outputPath: 'C:/exports/cut.mp4',
      profile: {
        format: 'mp4',
        fps: 'thirty',
        videoQuality: null,
        audioBitrateKbps: null,
        compressionMode: 'standard',
      },
      snapshot: null,
    };
    expect(timelineExportRequestSchema.safeParse(raw).success).toBe(false);
  });

  it('accepts the null timeline-export acknowledgement and rejects a non-null one', () => {
    expect(parseTimelineExportResponse('process_timeline_export', null)).toBeNull();
    expectCommandError(
      () => parseTimelineExportResponse('process_timeline_export', 0),
      'process_timeline_export',
    );
  });
});
