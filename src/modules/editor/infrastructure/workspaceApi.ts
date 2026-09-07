/**
 * Workspace per-module infrastructure API (Blueprint §2.2, Phase 7).
 *
 * The only layer allowed to touch `bindings.commands` for workspace mutations.
 * Each notify function sends one command, unwraps the Tauri result with the
 * shared {@link unwrapCommand} helper, and logs backend failures with the same
 * messages as the previous application-layer transport. Fire-and-forget: these
 * never throw; the optimistic store update always happens in the caller.
 */
import { commands } from '../../../domain/ipc/bindings';
import type {
  EditorWorkspaceState as RustEditorWorkspaceState,
  RenderProfilePayload,
} from '../../../domain/ipc/bindings';
import { unwrapCommand } from '../../../infrastructure/ipc-unwrap';
import type { EditorAsset, RenderProfile } from '../domain/model';

function logCommandError(action: string, detail: unknown): void {
  console.error(`Failed to ${action} in Rust workspace:`, detail);
}

export async function fetchAppState(): Promise<RustEditorWorkspaceState> {
  return unwrapCommand(commands.getAppState(), 'get_app_state');
}

export async function notifyWorkspaceAddFiles(assets: EditorAsset[]): Promise<void> {
  try {
    await unwrapCommand(commands.workspaceAddFiles(assets), 'workspace_add_files');
  } catch (error) {
    logCommandError('add files to Rust workspace', error);
  }
}

export async function notifyWorkspaceRemoveFile(fileId: string): Promise<void> {
  try {
    await unwrapCommand(commands.workspaceRemoveFile(fileId), 'workspace_remove_file');
  } catch (error) {
    logCommandError('remove file from Rust workspace', error);
  }
}

export async function notifyWorkspaceSetActiveFile(fileId: string): Promise<void> {
  try {
    await unwrapCommand(commands.workspaceSetActiveFile(fileId), 'workspace_set_active_file');
  } catch (error) {
    logCommandError('set active file in Rust workspace', error);
  }
}

export async function notifyWorkspaceMoveClip(
  fileId: string,
  clipId: string,
  startMs: number,
): Promise<void> {
  try {
    await unwrapCommand(
      commands.workspaceMoveClip(fileId, clipId, startMs),
      'workspace_move_clip',
    );
  } catch (error) {
    logCommandError('move clip in Rust workspace', error);
  }
}

export async function notifyWorkspaceTrimClipStart(
  fileId: string,
  clipId: string,
  inPointMs: number,
  newStartMs: number,
): Promise<void> {
  try {
    await unwrapCommand(
      commands.workspaceTrimClipStart(fileId, clipId, inPointMs, newStartMs),
      'workspace_trim_clip_start',
    );
  } catch (error) {
    logCommandError('trim clip start in Rust workspace', error);
  }
}

export async function notifyWorkspaceTrimClipEnd(
  fileId: string,
  clipId: string,
  outPointMs: number,
): Promise<void> {
  try {
    await unwrapCommand(
      commands.workspaceTrimClipEnd(fileId, clipId, outPointMs),
      'workspace_trim_clip_end',
    );
  } catch (error) {
    logCommandError('trim clip end in Rust workspace', error);
  }
}

export async function notifyWorkspaceSplitClip(
  fileId: string,
  clipId: string,
  atMs: number,
): Promise<void> {
  try {
    await unwrapCommand(
      commands.workspaceSplitClip(fileId, clipId, atMs),
      'workspace_split_clip',
    );
  } catch (error) {
    logCommandError('split clip in Rust workspace', error);
  }
}

export async function notifyWorkspaceDeleteClips(
  fileId: string,
  clipIds: string[],
): Promise<void> {
  try {
    await unwrapCommand(
      commands.workspaceDeleteClips(fileId, clipIds),
      'workspace_delete_clips',
    );
  } catch (error) {
    logCommandError('delete clips in Rust workspace', error);
  }
}

export async function notifyWorkspaceSetClipsMuted(
  fileId: string,
  clipIds: string[],
  muted: boolean,
): Promise<void> {
  try {
    await unwrapCommand(
      commands.workspaceSetClipsMuted(fileId, clipIds, muted),
      'workspace_set_clips_muted',
    );
  } catch (error) {
    logCommandError('mute clips in Rust workspace', error);
  }
}

function toRenderProfilePayload(
  patch: Partial<RenderProfile>,
  base: RenderProfile,
): RenderProfilePayload {
  return {
    format: patch.format ?? base.format,
    fps: patch.fps ?? base.fps,
    videoQuality: patch.videoQuality ?? base.videoQuality ?? null,
    audioBitrateKbps: patch.audioBitrateKbps ?? base.audioBitrateKbps ?? null,
    compressionMode: patch.compressionMode ?? base.compressionMode ?? 'standard',
  };
}

export async function notifyWorkspaceSetRenderProfile(
  fileId: string,
  patch: Partial<RenderProfile>,
  base: RenderProfile,
): Promise<void> {
  try {
    await unwrapCommand(
      commands.workspaceSetRenderProfile(fileId, toRenderProfilePayload(patch, base)),
      'workspace_set_render_profile',
    );
  } catch (error) {
    logCommandError('set render profile in Rust workspace', error);
  }
}
