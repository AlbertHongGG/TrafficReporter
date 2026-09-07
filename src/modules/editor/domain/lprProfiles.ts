import rawCatalog from './lpr-analysis-profiles.json';
import type { LprAnalysisOptionsPayload } from '../../../platform/ipc/bindings';

export type LprAnalysisProfileId = string;

export interface LprAnalysisProfileDefinition {
  id: LprAnalysisProfileId;
  label: string;
  description: string;
  options: LprAnalysisOptionsPayload;
}

export interface LprAnalysisProfileCatalog {
  version: number;
  defaultProfileId: LprAnalysisProfileId;
  developerDiagnosticsOptions?: LprAnalysisOptionsPayload | null;
  profiles: LprAnalysisProfileDefinition[];
}

const catalog = rawCatalog as LprAnalysisProfileCatalog;

export const lprAnalysisProfileCatalog = catalog;
export const defaultLprAnalysisProfileId = catalog.defaultProfileId;

export function getLprAnalysisProfiles(): LprAnalysisProfileDefinition[] {
  return catalog.profiles;
}

export function getLprAnalysisProfile(profileId: LprAnalysisProfileId | null | undefined): LprAnalysisProfileDefinition {
  return catalog.profiles.find((profile) => profile.id === profileId)
    ?? catalog.profiles.find((profile) => profile.id === catalog.defaultProfileId)
    ?? catalog.profiles[0]!;
}

export function getLprAnalysisProfileLabel(profileId: LprAnalysisProfileId | null | undefined) {
  return getLprAnalysisProfile(profileId).label;
}
