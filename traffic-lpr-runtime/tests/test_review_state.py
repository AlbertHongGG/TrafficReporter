from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.domain.models import AnalysisProvenance, PlateCandidate, ReviewState


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
    def test_evaluate_review_state_marks_accepted_candidate(self) -> None:
        state = ReviewState.evaluate(
            [_candidate('candidate-1')],
            'candidate-1',
            {
                'acceptedCandidateId': 'candidate-1',
                'suggestedCandidateId': 'candidate-1',
                'reviewRequired': False,
                'reasons': [],
            },
        )

        self.assertEqual(state.status, 'accepted')
        self.assertEqual(state.accepted_candidate_id, 'candidate-1')
        self.assertEqual(state.suggested_candidate_id, 'candidate-1')
        self.assertEqual(state.reasons, [])

        payload = state.to_payload()
        self.assertEqual(payload['status'], 'accepted')
        self.assertEqual(payload['acceptedCandidateId'], 'candidate-1')
        self.assertEqual(payload['suggestedCandidateId'], 'candidate-1')
        self.assertEqual(payload['reasons'], [])

    def test_evaluate_review_state_marks_review_required(self) -> None:
        state = ReviewState.evaluate(
            [_candidate('candidate-1'), _candidate('candidate-2', text='ABD1234')],
            None,
            {
                'suggestedCandidateId': 'candidate-2',
                'reviewRequired': True,
                'reasons': ['low-margin'],
            },
        )

        self.assertEqual(state.status, 'review-required')
        self.assertIsNone(state.accepted_candidate_id)
        self.assertEqual(state.suggested_candidate_id, 'candidate-2')
        self.assertEqual(state.reasons, ['low-margin'])

        payload = state.to_payload()
        self.assertEqual(payload['status'], 'review-required')
        self.assertIsNone(payload['acceptedCandidateId'])
        self.assertEqual(payload['suggestedCandidateId'], 'candidate-2')
        self.assertEqual(payload['reasons'], ['low-margin'])

    def test_evaluate_review_state_keeps_accepted_candidate_when_review_is_still_required(self) -> None:
        state = ReviewState.evaluate(
            [_candidate('candidate-1'), _candidate('candidate-2', text='ABD1234')],
            'candidate-1',
            {
                'acceptedCandidateId': 'candidate-1',
                'suggestedCandidateId': 'candidate-1',
                'reviewRequired': True,
                'reasons': ['tracking-ambiguity'],
            },
        )

        self.assertEqual(state.status, 'review-required')
        self.assertEqual(state.accepted_candidate_id, 'candidate-1')
        self.assertEqual(state.suggested_candidate_id, 'candidate-1')
        self.assertEqual(state.reasons, ['tracking-ambiguity'])

    def test_evaluate_review_state_marks_no_candidate_when_runtime_returns_none(self) -> None:
        state = ReviewState.evaluate([], None, None)

        self.assertEqual(state.status, 'no-candidate')
        self.assertIsNone(state.accepted_candidate_id)
        self.assertIsNone(state.suggested_candidate_id)
        self.assertEqual(state.reasons, ['no-candidate'])

    def test_create_analysis_provenance_uses_runtime_and_request_context(self) -> None:
        before = time.time_ns() // 1_000_000
        provenance = AnalysisProvenance.create(
            'analyze-frame',
            {
                'requestId': 'req-001',
                'analysisProfileId': 'precision',
                'enableDeveloperDiagnostics': True,
            },
            {'version': 'runtime-1.2.3'},
        )
        after = time.time_ns() // 1_000_000

        self.assertEqual(provenance.request_id, 'req-001')
        self.assertEqual(provenance.command, 'analyze-frame')
        self.assertEqual(provenance.analysis_profile_id, 'precision')
        self.assertTrue(provenance.developer_diagnostics_enabled)
        self.assertEqual(provenance.runtime_version, 'runtime-1.2.3')
        self.assertGreaterEqual(provenance.emitted_at_ms, before)
        self.assertLessEqual(provenance.emitted_at_ms, after)

        payload = provenance.to_payload()
        self.assertEqual(payload['requestId'], 'req-001')
        self.assertEqual(payload['command'], 'analyze-frame')
        self.assertEqual(payload['analysisProfileId'], 'precision')
        self.assertTrue(payload['developerDiagnosticsEnabled'])
        self.assertEqual(payload['runtimeVersion'], 'runtime-1.2.3')

    def test_create_analysis_provenance_includes_resolved_runtime_options(self) -> None:
        provenance = AnalysisProvenance.create(
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

        self.assertEqual(provenance.restoration_mode, 'classical')
        self.assertEqual(provenance.recognizer_backend, 'hybrid')
        self.assertEqual(provenance.temporal_evidence_mode, 'motion-aware')
        self.assertEqual(provenance.sequence_review_mode, 'strict')

        payload = provenance.to_payload()
        self.assertEqual(payload['restorationMode'], 'classical')
        self.assertEqual(payload['recognizerBackend'], 'hybrid')
        self.assertEqual(payload['temporalEvidenceMode'], 'motion-aware')
        self.assertEqual(payload['sequenceReviewMode'], 'strict')


if __name__ == '__main__':
    unittest.main()