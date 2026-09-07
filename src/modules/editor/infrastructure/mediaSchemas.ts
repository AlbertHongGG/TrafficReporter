/**
 * Phase 2-B IPC boundary schemas — editor media + AI-panel asset module
 * (Blueprint §2.3).
 *
 * Every payload crossing the Rust/Python → frontend process boundary is
 * validated exactly once here, in the infrastructure layer, right after
 * {@link unwrapCommand} and before any mapper/domain code sees it. Covers:
 * - `probe_media_source` → {@link MediaProbePayload} (media probing)
 * - `export_frame_image` → `null` (frame export acknowledgement)
 * - `save_generated_media_asset` → `null` (AI-panel asset acknowledgement)
 *
 * Each schema mirrors its wire shape in `src/platform/ipc/bindings.ts`:
 * wire-nullable fields stay `.nullable()` in the schema; domain-side
 * defaults (`??` convergence, e.g. `probe.durationMs ?? 0`) are unchanged
 * and live in the API functions, not here.
 *
 * Validation failures throw {@link IpcCommandError} whose message carries
 * the command name plus a zod issue summary.
 */

import { z } from 'zod';

import type { MediaProbePayload } from '../../../platform/ipc/bindings';
import { IpcCommandError } from '../../../platform/ipc/ipc-unwrap';

export const mediaProbePayloadSchema = z.object({
  durationMs: z.number().nullable(),
  hasVideo: z.boolean(),
  hasAudio: z.boolean(),
  fps: z.number().nullable(),
  audioBitrateKbps: z.number().nullable(),
  width: z.number().nullable(),
  height: z.number().nullable(),
});

/** `export_frame_image` resolves with `null` on success. */
export const frameExportResponseSchema = z.null();

/** `save_generated_media_asset` resolves with `null` on success. */
export const saveGeneratedMediaAssetResponseSchema = z.null();

export type ValidatedMediaProbePayload = z.infer<typeof mediaProbePayloadSchema>;

// Compile-time pin: schema output must stay assignable to the bindings wire
// type. If bindings drift, tsc fails on the alias below — not silently at
// runtime.
type AssertMediaWireShapes<T extends MediaProbePayload> = T;
export type PinnedMediaWireShapes = AssertMediaWireShapes<ValidatedMediaProbePayload>;

function formatIssues(error: z.ZodError): string {
  return error.issues
    .map((issue) => {
      const path = issue.path.map((segment) => String(segment)).join('.');
      return `${path === '' ? '(root)' : path}: ${issue.message}`;
    })
    .join('; ');
}

function throwValidationError(command: string, error: z.ZodError): never {
  throw new IpcCommandError('command', command, `response validation failed: ${formatIssues(error)}`);
}

export function parseMediaProbeResponse(command: string, raw: unknown): MediaProbePayload {
  const parsed = mediaProbePayloadSchema.safeParse(raw);
  if (!parsed.success) {
    throwValidationError(command, parsed.error);
  }
  return parsed.data;
}

export function parseFrameExportResponse(command: string, raw: unknown): null {
  const parsed = frameExportResponseSchema.safeParse(raw);
  if (!parsed.success) {
    throwValidationError(command, parsed.error);
  }
  return parsed.data;
}

export function parseSaveGeneratedMediaAssetResponse(command: string, raw: unknown): null {
  const parsed = saveGeneratedMediaAssetResponseSchema.safeParse(raw);
  if (!parsed.success) {
    throwValidationError(command, parsed.error);
  }
  return parsed.data;
}
