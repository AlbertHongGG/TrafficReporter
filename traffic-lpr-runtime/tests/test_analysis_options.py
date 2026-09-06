from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.application.contracts.options_factory import build_analysis_options_from_payload
from traffic_lpr_runtime.application.contracts.profiles import load_analysis_profile_catalog
from traffic_lpr_runtime.domain.analysis_options import AnalysisOptions


class AnalysisOptionsTests(unittest.TestCase):
    def setUp(self) -> None:
        load_analysis_profile_catalog.cache_clear()

    def tearDown(self) -> None:
        load_analysis_profile_catalog.cache_clear()

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


if __name__ == '__main__':
    unittest.main()
