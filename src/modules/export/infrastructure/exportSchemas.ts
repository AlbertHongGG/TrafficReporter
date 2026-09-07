/**
 * Phase 2-B IPC boundary schemas — export module (Blueprint §2.3).
 *
 * Every payload crossing the Rust/Python → frontend process boundary is
 * validated exactly once here, in the infrastructure layer, right after
 * {@link unwrapCommand} and before any mapper/domain code sees it. The
 * domain layer (`export/domain/model.ts`, whose `RenderProfile` /
 * `ExportSnapshot` are deliberately narrowed: `format: ExportFormat` etc.)
 * only receives already-clean objects.
 *
 * Each schema mirrors its `*Payload` wire shape in
 * `src/platform/ipc/bindings.ts`: wire-nullable fields stay `.nullable()` in
 * the schema; domain-side defaults (`??` convergence) are unchanged and live
 * in the existing request mappers, not here.
 *
 * Validation failures throw {@link IpcCommandError} whose message carries
 * the command name plus a zod issue summary.
 */

import { z } from 'zod';

import type {
  ExportSnapshotPayload,
  RenderProfilePayload,
  TimelineExportRequest,
} from '../../../platform/ipc/bindings';
import { IpcCommandError } from '../../../platform/ipc/ipc-unwrap';

export const outputCompressionModePayloadSchema = z.enum(['standard', 'compact']);

export const renderProfilePayloadSchema = z.object({
  format: z.string(),
  fps: z.number(),
  videoQuality: z.string().nullable(),
  audioBitrateKbps: z.number().nullable(),
  compressionMode: outputCompressionModePayloadSchema,
});

export const exportSourceSchema = z.object({
  id: z.string(),
  name: z.string(),
  path: z.string(),
  hasVideo: z.boolean(),
  hasAudio: z.boolean(),
  width: z.number().nullable(),
  height: z.number().nullable(),
});

export const timelineTrackPayloadSchema = z.object({
  id: z.string(),
  name: z.string(),
  order: z.number(),
});

export const timelineClipPayloadSchema = z.object({
  id: z.string(),
  assetId: z.string(),
  trackId: z.string(),
  startMs: z.number().nullable(),
  inPointMs: z.number().nullable(),
  outPointMs: z.number().nullable(),
  muted: z.boolean(),
});

export const exportSnapshotPayloadSchema = z.object({
  fileId: z.string(),
  fileName: z.string(),
  workspaceName: z.string(),
  suggestedName: z.string(),
  timelineDurationMs: z.number().nullable(),
  hasVideo: z.boolean(),
  hasAudio: z.boolean(),
  dominantWidth: z.number().nullable(),
  dominantHeight: z.number().nullable(),
  sources: z.array(exportSourceSchema),
  tracks: z.array(timelineTrackPayloadSchema),
  clips: z.array(timelineClipPayloadSchema),
  renderProfile: renderProfilePayloadSchema,
});

export const timelineExportRequestSchema = z.object({
  outputPath: z.string(),
  profile: renderProfilePayloadSchema,
  snapshot: exportSnapshotPayloadSchema,
});

/** `process_timeline_export` resolves with `null` on success. */
export const timelineExportResponseSchema = z.null();

export type ValidatedRenderProfilePayload = z.infer<typeof renderProfilePayloadSchema>;
export type ValidatedExportSnapshotPayload = z.infer<typeof exportSnapshotPayloadSchema>;
export type ValidatedTimelineExportRequest = z.infer<typeof timelineExportRequestSchema>;

// Compile-time pins: schema output must stay assignable to the bindings
// wire types. If bindings drift, tsc fails on the alias below — not silently
// at runtime.
type AssertExportWireShapes<
  T extends RenderProfilePayload,
  U extends ExportSnapshotPayload,
  V extends TimelineExportRequest,
> = [T, U, V];
export type PinnedExportWireShapes = AssertExportWireShapes<
  ValidatedRenderProfilePayload,
  ValidatedExportSnapshotPayload,
  ValidatedTimelineExportRequest
>;

function formatIssues(error: z.ZodError): string {
  return error.issues
    .map((issue) => {
      const path = issue.path.map((segment) => String(segment)).join('.');
      return `${path === '' ? '(root)' : path}: ${issue.message}`;
    })
    .join('; ');
}

export function parseTimelineExportResponse(command: string, raw: unknown): null {
  const parsed = timelineExportResponseSchema.safeParse(raw);
  if (!parsed.success) {
    throw new IpcCommandError(
      'command',
      command,
      `response validation failed: ${formatIssues(parsed.error)}`,
    );
  }
  return parsed.data;
}
