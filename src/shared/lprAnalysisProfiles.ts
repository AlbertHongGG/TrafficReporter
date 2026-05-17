import rawCatalog from './config/lpr-analysis-profiles.json';
import type {
  LprAnalysisProfileCatalog,
  LprAnalysisProfileDefinition,
  LprAnalysisProfileId,
} from './contracts';

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
