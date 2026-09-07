/**
 * File-dialog infrastructure (Blueprint §4, Phase 4-D).
 *
 * The ONLY place in `modules/editor` allowed to touch the Tauri dialog
 * plugin. Workflow hooks call {@link promptLprEvidenceSavePath} for the
 * user-confirmed output path and hand it to the LPR evidence-export
 * use-case (which owns `.json` normalization + the export itself).
 */
import { save } from '@tauri-apps/plugin-dialog';

/**
 * Ask the user where to write the LPR evidence snapshot.
 * Returns the confirmed path, or `null` when the dialog is dismissed.
 */
export async function promptLprEvidenceSavePath(defaultPath: string): Promise<string | null> {
  const selectedPath = await save({
    title: 'Export LPR evidence snapshot',
    defaultPath,
    filters: [{ name: 'JSON', extensions: ['json'] }],
  });
  return selectedPath ?? null;
}
