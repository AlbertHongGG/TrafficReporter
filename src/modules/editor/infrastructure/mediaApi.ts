import { convertFileSrc } from '@tauri-apps/api/core';
import { commands, type EditorAsset, type FrameExportRequest, type MediaProbePayload } from '../../../platform/ipc/bindings';
import { unwrapCommand } from '../../../platform/ipc/ipc-unwrap';
import { parseFrameExportResponse, parseMediaProbeResponse } from './mediaSchemas';
import { basename, createId, extensionOf } from '../domain/model';

const SUPPORTED_EXTENSIONS = new Set([
  'mp4',
  'mkv',
  'mov',
  'webm',
  'avi',
  'm4v',
]);

const THUMBNAIL_CAPTURE_TIMEOUT_MS = 1500;

export function isSupportedMediaPath(path: string) {
  return SUPPORTED_EXTENSIONS.has(extensionOf(path));
}

async function captureVideoThumbnail(url: string, durationMs: number) {
  return new Promise<string | null>((resolve) => {
    const video = document.createElement('video');
    const canvas = document.createElement('canvas');
    let settled = false;

    const timeoutId = window.setTimeout(() => finish(null), THUMBNAIL_CAPTURE_TIMEOUT_MS);

    const finish = (value: string | null) => {
      if (settled) {
        return;
      }

      settled = true;
      window.clearTimeout(timeoutId);
      video.pause();
      video.removeAttribute('src');
      video.load();
      resolve(value);
    };

    const drawFrame = () => {
      const width = video.videoWidth || 320;
      const height = video.videoHeight || 180;
      if (width <= 0 || height <= 0) {
        finish(null);
        return;
      }

      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext('2d');
      if (!context) {
        finish(null);
        return;
      }

      try {
        context.drawImage(video, 0, 0, width, height);
        finish(canvas.toDataURL('image/jpeg', 0.76));
      } catch {
        // Asset protocol videos can taint the canvas; thumbnail capture must never block import.
        finish(null);
      }
    };

    video.addEventListener('error', () => finish(null), { once: true });
    video.addEventListener(
      'loadedmetadata',
      () => {
        const seekTargetSeconds = Math.min(1, Math.max(0.05, durationMs / 2000));
        if (!Number.isFinite(video.duration) || video.duration <= seekTargetSeconds) {
          drawFrame();
          return;
        }

        video.addEventListener('seeked', drawFrame, { once: true });
        try {
          video.currentTime = seekTargetSeconds;
        } catch {
          finish(null);
        }
      },
      { once: true },
    );

    video.crossOrigin = 'anonymous';
    video.muted = true;
    video.preload = 'metadata';
    video.playsInline = true;
    video.src = url;
    video.load();
  });
}

export async function probePath(path: string): Promise<MediaProbePayload> {
  const raw = await unwrapCommand(commands.probeMediaSource(path), 'probe_media_source');
  return parseMediaProbeResponse('probe_media_source', raw);
}

export async function exportFrameImage(request: FrameExportRequest): Promise<void> {
  const raw = await unwrapCommand(
    commands.exportFrameImage({
      ...request,
      timeMs: Math.max(0, Math.round(request.timeMs ?? 0)),
    }),
    'export_frame_image',
  );
  parseFrameExportResponse('export_frame_image', raw);
}

export async function buildEditorAsset(path: string): Promise<EditorAsset> {
  const probe = await probePath(path);
  if (!probe.hasVideo) {
    throw new Error('Only video files are supported in this editor.');
  }

  const durationMs = probe.durationMs ?? 0;
  const url = convertFileSrc(path);
  let thumbnailUrl: string | null = null;
  try {
    thumbnailUrl = await captureVideoThumbnail(url, durationMs);
  } catch {
    // Ignore thumbnail generation errors; fallback to null
  }

  return {
    id: createId('asset'),
    name: basename(path),
    path,
    kind: 'video',
    durationMs,
    hasVideo: probe.hasVideo,
    hasAudio: probe.hasAudio,
    fps: probe.fps ?? null,
    audioBitrateKbps: probe.audioBitrateKbps ?? null,
    width: probe.width ?? null,
    height: probe.height ?? null,
    status: 'ready',
    url,
    thumbnailUrl,
    fileSize: 0,
    createdAt: '',
    modifiedAt: '',
  };
}
