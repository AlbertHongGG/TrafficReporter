from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.application.analysis_policy import AnalysisPolicyResolver
from traffic_lpr_runtime.domain.analysis_options import AnalysisOptions


class AnalysisPolicyTests(unittest.TestCase):
    def test_short_interval_policy_normalizes_legacy_ui_sampling(self) -> None:
        policy = AnalysisPolicyResolver().resolve_interval(
            {
                'interval': {'startMs': 0, 'endMs': 3000},
                'analysisIntent': 'interactive-range',
                'sampleEveryMs': 214,
                'maxSamples': 14,
            },
            AnalysisOptions(analysis_profile_id='precision'),
        )

        self.assertEqual(policy.intent, 'interactive-short-range')
        self.assertEqual(policy.sample_every_ms, 150)
        self.assertEqual(policy.max_samples, 16)
        self.assertIn('caller-sampling-normalized', policy.rules)

    def test_interactive_dense_range_policy_is_resolved_in_runtime(self) -> None:
        policy = AnalysisPolicyResolver().resolve_interval(
            {
                'interval': {'startMs': 0, 'endMs': 8400},
                'analysisIntent': 'interactive-dense-range',
            },
            AnalysisOptions(analysis_profile_id='precision'),
        )

        self.assertEqual(policy.intent, 'interactive-dense-range')
        self.assertEqual(policy.max_samples, 24)
        self.assertEqual(policy.sample_every_ms, 300)
        self.assertIn('interactive-dense-range-grid', policy.rules)

    def test_ai_evidence_policy_uses_shared_runtime_resolver(self) -> None:
        policy = AnalysisPolicyResolver().resolve_interval(
            {
                'interval': {'startMs': 1000, 'endMs': 9000},
                'analysisIntent': 'ai-evidence-range',
            },
            AnalysisOptions(analysis_profile_id='precision'),
        )

        self.assertEqual(policy.intent, 'ai-evidence-range')
        self.assertEqual(policy.max_samples, 17)
        self.assertEqual(policy.sample_every_ms, 471)
        self.assertEqual(policy.latency_budget_ms, 45_000)


if __name__ == '__main__':
    unittest.main()