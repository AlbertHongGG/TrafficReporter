from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.application.contracts.options_factory import build_analysis_options_from_payload
from traffic_lpr_runtime.domain.analysis_options import AnalysisOptions
from traffic_lpr_runtime.domain.profiles import AnalysisProfileCatalog, AnalysisProfileId


class AnalysisOptionsTests(unittest.TestCase):
    def test_precision_profile_exposes_strict_temporal_review_envelope(self) -> None:
        options = build_analysis_options_from_payload({'analysisProfileId': 'precision'})

        self.assertEqual(options.recognizer_backend, 'hybrid')
        self.assertEqual(options.temporal_evidence_mode, 'motion-aware')
        self.assertEqual(options.sequence_review_mode, 'strict')
        self.assertEqual(options.min_sequence_persistence, 0.72)
        self.assertEqual(options.max_sequence_gap_count, 0)

    def test_payload_can_override_current_feature_routing_options(self) -> None:
        options = build_analysis_options_from_payload({
            'analysisProfileId': 'balanced',
            'analysisOptions': {
                'recognizerBackend': 'baseline',
                'temporalEvidenceMode': 'scheduled',
                'sequenceReviewMode': 'relaxed',
                'minSequencePersistence': 0.41,
                'maxSequenceGapCount': 3,
            },
        })

        self.assertEqual(options.recognizer_backend, 'baseline')
        self.assertEqual(options.temporal_evidence_mode, 'scheduled')
        self.assertEqual(options.sequence_review_mode, 'relaxed')
        self.assertEqual(options.min_sequence_persistence, 0.41)
        self.assertEqual(options.max_sequence_gap_count, 3)

    def test_domain_profile_catalog_pure_in_memory_resolution(self) -> None:
        resolved_id, precision_opts = AnalysisProfileCatalog.resolve_profile_options(AnalysisProfileId.PRECISION.value)
        self.assertEqual(resolved_id, 'precision')
        self.assertEqual(precision_opts['sequenceReviewMode'], 'strict')
        self.assertEqual(precision_opts['temporalWindowMs'], 260)

        resolved_id, balanced_opts = AnalysisProfileCatalog.resolve_profile_options(AnalysisProfileId.BALANCED.value)
        self.assertEqual(resolved_id, 'balanced')
        self.assertEqual(balanced_opts['sequenceReviewMode'], 'balanced')
        self.assertEqual(balanced_opts['temporalWindowMs'], 220)

        resolved_id, recovery_opts = AnalysisProfileCatalog.resolve_profile_options(AnalysisProfileId.RECOVERY.value)
        self.assertEqual(resolved_id, 'recovery')
        self.assertEqual(recovery_opts['sequenceReviewMode'], 'relaxed')
        self.assertEqual(recovery_opts['temporalWindowMs'], 340)

        # Fallback to default precision on unknown profile
        fallback_id, fallback_opts = AnalysisProfileCatalog.resolve_profile_options('non-existent-profile')
        self.assertEqual(fallback_id, 'precision')
        self.assertEqual(fallback_opts['sequenceReviewMode'], 'strict')

    def test_developer_diagnostics_options_injection(self) -> None:
        _, dev_opts = AnalysisProfileCatalog.resolve_profile_options('precision', enable_developer_diagnostics=True)
        self.assertTrue(dev_opts['persistArtifacts'])
        self.assertEqual(dev_opts['debugTag'], 'developer-diagnostics')
        self.assertEqual(dev_opts['maxPlateCandidates'], 5)


if __name__ == '__main__':
    unittest.main()
