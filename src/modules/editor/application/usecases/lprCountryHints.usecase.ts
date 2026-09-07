/**
 * LPR country-hints use-case (Phase 4-A, extracted from `useLprWorkflow`).
 *
 * Pure function: parses a comma-separated hint draft and stores the result.
 */
import {
  defaultLprPorts,
  lprOk,
  parseCountryHints,
  type LprPorts,
  type LprResult,
} from './lprPorts.usecase';

export interface LprApplyCountryHintsInput {
  /** Unsaved draft (null falls back to the session hints, normalizing them). */
  draft: string | null;
}

export interface LprApplyCountryHintsData {
  countryHints: string[];
}

export function runLprApplyCountryHints(
  input: LprApplyCountryHintsInput,
  ports: LprPorts = defaultLprPorts,
): LprResult<LprApplyCountryHintsData> {
  const countryHints = parseCountryHints(
    input.draft ?? ports.readLprSession().countryHints.join(', '),
  );
  ports.actions.setLprCountryHints(countryHints);
  return lprOk({ countryHints });
}
