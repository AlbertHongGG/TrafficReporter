from __future__ import annotations

import unittest

from traffic_lpr_runtime.domain.enums import (
    AnchorStatus,
    ArtifactStage,
    DecisionSource,
    EvidenceReason,
    JobStatus,
    TrackingTier,
    VehicleKind,
)


class ContractConformanceTestCase(unittest.TestCase):
    def test_evidence_reasons_contain_all_variants(self) -> None:
        expected = {
            'anchor',
            'anchor-frame',
            'interval-start',
            'interval-end',
            'scheduled-sample',
            'temporal-burst',
            'motion-hotspot',
            'high-confidence',
            'highest-confidence',
            'highest-resolution',
            'representative',
            'temporal-support',
            'sharpness-peak',
        }
        actual = {reason.value for reason in EvidenceReason}
        self.assertEqual(actual, expected)

    def test_decision_sources_contain_all_variants(self) -> None:
        expected = {
            'single-frame',
            'temporal-fusion',
            'cross-frame-vote',
            'user-selected',
            'fused-image',
            'fused-char',
            'temporal-restored',
            'support-carry',
            'legacy-vote',
        }
        actual = {source.value for source in DecisionSource}
        self.assertEqual(actual, expected)

    def test_artifact_stages_contain_all_variants(self) -> None:
        expected = {
            'raw',
            'original',
            'rectified',
            'enhanced',
            'restored',
            'temporal-restored',
            'fused',
        }
        actual = {stage.value for stage in ArtifactStage}
        self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
