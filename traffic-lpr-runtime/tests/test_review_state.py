from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.application.provenance import build_analysis_provenance
from traffic_lpr_runtime.application.review_state import build_review_state
from traffic_lpr_runtime.domain.models import PlateCandidate


def _candidate(candidate_id: str, text: str = 'ABC1234') -> PlateCandidate:
    return PlateCandidate(
        id=candidate_id,
        text=text,
        confidence=0.95,
        source='fused',
        frame_time_ms=100,
        country_code='tw',
        box=None,
        quality=None,
        diagnostics=None,
    )


class ReviewStateTests(unittest.TestCase):
    def test_build_review_state_marks_accepted_candidate(self) -> None:
        review = build_review_state(
            [_candidate('candidate-1')],
            'candidate-1',
            {
                'acceptedCandidateId': 'candidate-1',
                'suggestedCandidateId': 'candidate-1',
                'reviewRequired': False,
                'reasons': [],
            },
        )

        self.assertEqual(review['status'], 'accepted')
        self.assertEqual(review['acceptedCandidateId'], 'candidate-1')
        self.assertEqual(review['suggestedCandidateId'], 'candidate-1')
        self.assertEqual(review['reasons'], [])

    def test_build_review_state_marks_review_required(self) -> None:
        review = build_review_state(
            [_candidate('candidate-1'), _candidate('candidate-2', text='ABD1234')],
            None,
            {
                'suggestedCandidateId': 'candidate-2',
                'reviewRequired': True,
                'reasons': ['low-margin'],
            },
        )

        self.assertEqual(review['status'], 'review-required')
        self.assertIsNone(review['acceptedCandidateId'])
        self.assertEqual(review['suggestedCandidateId'], 'candidate-2')
        self.assertEqual(review['reasons'], ['low-margin'])

    def test_build_review_state_marks_no_candidate_when_runtime_returns_none(self) -> None:
        review = build_review_state([], None, None)

        self.assertEqual(review['status'], 'no-candidate')
        self.assertIsNone(review['acceptedCandidateId'])
        self.assertIsNone(review['suggestedCandidateId'])
        self.assertEqual(review['reasons'], ['no-candidate'])

    def test_build_analysis_provenance_uses_runtime_and_request_context(self) -> None:
        before = time.time_ns() // 1_000_000
        provenance = build_analysis_provenance(
            'analyze-frame',
            {
                'requestId': 'req-001',
                'analysisProfileId': 'precision',
                'enableDeveloperDiagnostics': True,
            },
            {'version': 'runtime-1.2.3'},
        )
        after = time.time_ns() // 1_000_000

        self.assertEqual(provenance['requestId'], 'req-001')
        self.assertEqual(provenance['command'], 'analyze-frame')
        self.assertEqual(provenance['analysisProfileId'], 'precision')
        self.assertTrue(provenance['developerDiagnosticsEnabled'])
        self.assertEqual(provenance['runtimeVersion'], 'runtime-1.2.3')
        self.assertGreaterEqual(provenance['emittedAtMs'], before)
        self.assertLessEqual(provenance['emittedAtMs'], after)

    def test_build_analysis_provenance_includes_resolved_runtime_options(self) -> None:
        provenance = build_analysis_provenance(
            'analyze-interval',
            {'requestId': 'req-002'},
            {'version': 'runtime-1.2.3'},
            {
                'restorationMode': 'classical',
                'recognizerBackend': 'hybrid',
                'temporalEvidenceMode': 'motion-aware',
                'sequenceReviewMode': 'strict',
            },
        )

        self.assertEqual(provenance['restorationMode'], 'classical')
        self.assertEqual(provenance['recognizerBackend'], 'hybrid')
        self.assertEqual(provenance['temporalEvidenceMode'], 'motion-aware')
        self.assertEqual(provenance['sequenceReviewMode'], 'strict')



if __name__ == '__main__':
    unittest.main()