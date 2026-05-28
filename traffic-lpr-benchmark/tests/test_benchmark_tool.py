from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


TOOL_ROOT = Path(__file__).resolve().parents[1]
if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))
RUNTIME_ROOT = TOOL_ROOT.parent / 'traffic-lpr-runtime'
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from gate import evaluate_runtime_result_gate
from legacy_import import import_legacy_manifest
from analysis import build_run_analysis
from evaluation import build_run_evaluation
from registry import build_suite_registry, summarize_suite_registry
from profile_sweep import apply_analysis_profile_to_suite, build_profile_sweep_payload
from reporting import write_run_artifacts
from runtime_bridge import RuntimeInvokeError, build_runtime_request_envelope, unwrap_runtime_response
from traffic_lpr_runtime.application.benchmark_workflow import BenchmarkRunWorkflow, _evaluate_localization, summarize_benchmark_results
from validation import ValidationError, inspect_suite_payload, validate_profile_catalog_file, validate_suite_payload


class BenchmarkToolTests(unittest.TestCase):
    def test_validate_suite_payload_accepts_valid_frame_suite(self) -> None:
        payload = {
            'schemaVersion': 1,
            'suiteId': 'frame-suite',
            'title': 'Frame Suite',
            'analysisProfileId': 'precision',
            'cases': [
                {
                    'id': 'case-001',
                    'mode': 'frame',
                    'sourcePath': 'C:/tmp/frame.jpg',
                    'timeMs': 1200,
                    'expectedText': 'ABC1234',
                    'tags': ['taiwan'],
                    'metadata': {'dataset': 'AOLP', 'category': 'blur'},
                }
            ],
        }

        validate_suite_payload(payload)

    def test_validate_suite_payload_accepts_unreadable_frame_suite(self) -> None:
        payload = {
            'schemaVersion': 1,
            'suiteId': 'unreadable-suite',
            'title': 'Unreadable Suite',
            'analysisProfileId': 'precision',
            'cases': [
                {
                    'id': 'case-001',
                    'mode': 'frame',
                    'sourcePath': 'C:/tmp/frame.jpg',
                    'timeMs': 0,
                    'expectation': {'kind': 'unreadable'},
                    'tags': ['taiwan', 'lp2025'],
                    'metadata': {'dataset': 'LP2025', 'category': 'blur'},
                }
            ],
        }

        validate_suite_payload(payload)

    def test_validate_suite_payload_accepts_interval_suite_with_selected_target_track_id(self) -> None:
        payload = {
            'schemaVersion': 1,
            'suiteId': 'interval-suite',
            'analysisProfileId': 'precision',
            'cases': [
                {
                    'id': 'case-001',
                    'mode': 'interval',
                    'sourcePath': 'C:/tmp/track.mp4',
                    'anchorTimeMs': 1200,
                    'interval': {'startMs': 1000, 'endMs': 1600},
                    'selectedTargetBox': {'x': 0.1, 'y': 0.2, 'width': 0.3, 'height': 0.2},
                    'selectedTargetTrackId': 'target-1200-0',
                    'expectedText': 'ABC1234',
                    'metadata': {'dataset': 'local-dashcam', 'split': 'manual', 'category': 'tracking'},
                }
            ],
        }

        validate_suite_payload(payload)

    def test_validate_suite_payload_rejects_duplicate_case_ids(self) -> None:
        payload = {
            'schemaVersion': 1,
            'suiteId': 'duplicate-suite',
            'analysisProfileId': 'precision',
            'cases': [
                {'id': 'case-001', 'mode': 'frame', 'sourcePath': 'a', 'timeMs': 1, 'expectedText': 'AAA1111', 'metadata': {'dataset': 'AOLP', 'category': 'blur'}},
                {'id': 'case-001', 'mode': 'frame', 'sourcePath': 'b', 'timeMs': 2, 'expectedText': 'BBB2222', 'metadata': {'dataset': 'AOLP', 'category': 'night'}},
            ],
        }

        with self.assertRaises(ValidationError):
            validate_suite_payload(payload)

    def test_validate_suite_payload_rejects_missing_benchmark_semantics(self) -> None:
        payload = {
            'schemaVersion': 1,
            'suiteId': 'semantic-suite',
            'cases': [
                {
                    'id': 'case-001',
                    'mode': 'interval',
                    'sourcePath': 'track.mp4',
                    'expectedText': 'AAA1111',
                    'anchorTimeMs': 300,
                    'interval': {'startMs': 400, 'endMs': 800},
                    'selectedTargetBox': {'x': 0.1, 'y': 0.2, 'width': 0.3, 'height': 0.2},
                    'metadata': {'dataset': 'UFPR-ALPR'},
                }
            ],
        }

        with self.assertRaises(ValidationError) as error:
            validate_suite_payload(payload)

        self.assertIn('metadata.category or metadata.dominantCategory is required', str(error.exception))
        self.assertIn('analysisProfileId is required unless suite.analysisProfileId is declared', str(error.exception))
        self.assertIn('anchorTimeMs must lie within interval.startMs/endMs', str(error.exception))

    def test_runtime_request_envelope_uses_protocol_version(self) -> None:
        envelope = build_runtime_request_envelope('benchmark-run', {'cases': []}, request_id='req-001')

        self.assertEqual(envelope['protocolVersion'], 1)
        self.assertEqual(envelope['subcommand'], 'benchmark-run')
        self.assertEqual(envelope['requestId'], 'req-001')
        self.assertEqual(envelope['payload'], {'cases': []})

    def test_unwrap_runtime_response_rejects_protocol_mismatch(self) -> None:
        with self.assertRaises(RuntimeInvokeError):
            unwrap_runtime_response({'protocolVersion': 2, 'ok': True, 'result': {}})

    def test_unwrap_runtime_response_accepts_versioned_payload(self) -> None:
        result = unwrap_runtime_response({'protocolVersion': 1, 'ok': True, 'result': {'summary': 'ok'}})

        self.assertEqual(result, {'summary': 'ok'})

    def test_evaluate_runtime_result_gate_checks_tracking_survival_thresholds(self) -> None:
        gate = evaluate_runtime_result_gate(
            {
                'metrics': {
                    'totalCases': 2,
                    'meanTrackingCoverageRatio': 0.55,
                    'degradedTrackingRate': 0.5,
                    'intervalTrackingCaseCount': 2,
                    'latencyMs': {'p95': 1200.0},
                },
                'cases': [],
            },
            {
                'minExactRate': None,
                'minTop3Rate': None,
                'maxMeanCer': None,
                'maxReviewRequiredRate': None,
                'maxNoCandidateRate': None,
                'minPlateIou': None,
                'minMeanTrackingCoverageRatio': 0.7,
                'maxDegradedTrackingRate': 0.25,
                'maxP95LatencyMs': None,
            },
        )

        self.assertFalse(gate['passed'])
        self.assertEqual(
            {check['metric'] for check in gate['checks']},
            {'meanTrackingCoverageRatio', 'degradedTrackingRate'},
        )

    def test_evaluate_runtime_result_gate_checks_detection_fallback_acceptance(self) -> None:
        gate = evaluate_runtime_result_gate(
            {
                'metrics': {
                    'totalCases': 2,
                    'acceptedUnderDegradedTrackingRate': 0.0,
                    'detectionFallbackReviewRequiredRate': 1.0,
                    'latencyMs': {'p95': 1200.0},
                },
                'cases': [
                    {
                        'tracking': {'trackingTier': 'detection-fallback'},
                        'review': {'status': 'review-required'},
                    },
                    {
                        'tracking': {'trackingTier': 'full'},
                        'review': {'status': 'accepted'},
                    },
                ],
            },
            {
                'minExactRate': None,
                'minTop3Rate': None,
                'maxMeanCer': None,
                'maxReviewRequiredRate': None,
                'maxNoCandidateRate': None,
                'minPlateIou': None,
                'minMeanTrackingCoverageRatio': None,
                'maxDegradedTrackingRate': None,
                'minAcceptedUnderDegradedTrackingRate': 1.0,
                'maxDetectionFallbackReviewRequiredRate': 0.0,
                'maxP95LatencyMs': None,
            },
        )

        self.assertFalse(gate['passed'])
        self.assertEqual(
            {check['metric'] for check in gate['checks']},
            {'acceptedUnderDegradedTrackingRate', 'detectionFallbackReviewRequiredRate'},
        )

    def test_summarize_benchmark_results_includes_tracking_survival_metrics(self) -> None:
        summary = summarize_benchmark_results(
            [
                {
                    'id': 'case-001',
                    'exactMatch': True,
                    'top3Match': True,
                    'characterErrorRate': 0.0,
                    'acceptedConfidence': 0.9,
                    'acceptedMargin': 0.4,
                    'latencyMs': 100.0,
                    'failureReason': 'correct',
                    'bestSource': 'ocr:a',
                    'localization': {},
                    'trackMetrics': None,
                    'tracking': {
                        'trackingTier': 'full',
                        'coverageRatio': 1.0,
                        'trackedFrameCount': 8,
                        'reacquireFrames': 0,
                    },
                    'review': {'status': 'accepted', 'reasons': []},
                    'metadata': {'dataset': 'UFPR', 'split': 'smoke'},
                    'tags': [],
                },
                {
                    'id': 'case-002',
                    'exactMatch': True,
                    'top3Match': True,
                    'characterErrorRate': 0.0,
                    'acceptedConfidence': 0.88,
                    'acceptedMargin': 0.35,
                    'latencyMs': 120.0,
                    'failureReason': 'correct',
                    'bestSource': 'ocr:a',
                    'localization': {},
                    'trackMetrics': None,
                    'tracking': {
                        'trackingTier': 'detection-fallback',
                        'coverageRatio': 0.5,
                        'trackedFrameCount': 4,
                        'reacquireFrames': 2,
                    },
                    'review': {'status': 'review-required', 'reasons': ['coverage-gap']},
                    'metadata': {'dataset': 'UFPR', 'split': 'smoke'},
                    'tags': [],
                },
            ],
            {'status': 'ready'},
        )

        self.assertEqual(summary['metrics']['intervalTrackingCaseCount'], 2)
        self.assertEqual(summary['metrics']['trackingTierBreakdown'], {'detection-fallback': 1, 'full': 1})
        self.assertAlmostEqual(summary['metrics']['meanTrackingCoverageRatio'], 0.75)
        self.assertAlmostEqual(summary['metrics']['degradedTrackingRate'], 0.5)
        self.assertAlmostEqual(summary['metrics']['acceptedUnderDegradedTrackingRate'], 0.0)
        self.assertAlmostEqual(summary['metrics']['detectionFallbackReviewRequiredRate'], 1.0)
        self.assertAlmostEqual(summary['metrics']['meanDetectionFallbackReacquireFrames'], 2.0)
        self.assertAlmostEqual(summary['metrics']['meanTrackedFrameCount'], 6.0)

    def test_build_run_analysis_includes_tracking_acceptance_focus_breakdown(self) -> None:
        analysis = build_run_analysis({
            'runId': 'run-001',
            'suite': {'suiteId': 'suite-001', 'title': 'Suite'},
            'result': {
                'summary': 'demo',
                'metrics': {
                    'acceptedUnderDegradedTrackingRate': 0.5,
                    'detectionFallbackReviewRequiredRate': 0.25,
                    'meanDetectionFallbackReacquireFrames': 1.5,
                    'meanAcceptedMargin': 0.2,
                    'meanPredictionSwitchCount': 1.25,
                    'meanSampleExactMatchRate': 0.6,
                    'meanSequencePersistence': 0.55,
                    'meanCharacterConsistencyMean': 0.71,
                },
                'cases': [],
            },
        })

        self.assertIn('trackingAcceptance', analysis['focusBreakdown'])
        self.assertEqual(analysis['focusBreakdown']['trackingAcceptance']['acceptedUnderDegradedTrackingRate'], 0.5)
        self.assertEqual(analysis['focusBreakdown']['trackingAcceptance']['detectionFallbackReviewRequiredRate'], 0.25)
        self.assertEqual(analysis['focusBreakdown']['trackingAcceptance']['meanDetectionFallbackReacquireFrames'], 1.5)
        self.assertIn('hardCaseStability', analysis['focusBreakdown'])
        self.assertEqual(analysis['focusBreakdown']['hardCaseStability']['meanAcceptedMargin'], 0.2)
        self.assertEqual(analysis['focusBreakdown']['hardCaseStability']['meanPredictionSwitchCount'], 1.25)
        self.assertEqual(analysis['focusBreakdown']['hardCaseStability']['meanSampleExactMatchRate'], 0.6)
        self.assertEqual(analysis['focusBreakdown']['hardCaseStability']['meanSequencePersistence'], 0.55)
        self.assertEqual(analysis['focusBreakdown']['hardCaseStability']['meanCharacterConsistencyMean'], 0.71)

    def test_validate_profile_catalog_file_accepts_shared_catalog(self) -> None:
        catalog_path = TOOL_ROOT.parent / 'src' / 'shared' / 'config' / 'lpr-analysis-profiles.json'
        payload = validate_profile_catalog_file(catalog_path)
        self.assertEqual(payload['defaultProfileId'], 'precision')
        self.assertGreaterEqual(len(payload['profiles']), 1)

    def test_write_run_artifacts_writes_valid_bundle(self) -> None:
        suite_payload = {
            'schemaVersion': 1,
            'suiteId': 'bundle-suite',
            'title': 'Bundle Suite',
            'cases': [
                {'id': 'case-001', 'mode': 'frame', 'sourcePath': 'a', 'timeMs': 1, 'expectedText': 'AAA1111'}
            ],
        }
        runtime_result = {
            'summary': '1 case, exact=100.0%',
            'cases': [
                {
                    'id': 'case-001',
                    'mode': 'frame',
                    'expectationKind': 'readable',
                    'expectedText': 'AAA1111',
                    'bestText': 'AAA1111',
                    'bestSource': 'ocr:model-a',
                    'allSources': ['ocr:model-a'],
                    'top3Texts': ['AAA1111'],
                    'exactMatch': True,
                    'top3Match': True,
                    'characterErrorRate': 0.0,
                    'acceptedCandidateId': 'candidate-1',
                    'acceptedConfidence': 1.0,
                    'acceptedMargin': 1.0,
                    'latencyMs': 10.0,
                    'localization': {
                        'groundTruthFrameCount': 1,
                        'matchedFrameCount': 1,
                        'plateMeanIoU': 1.0,
                        'plateRecall': 1.0,
                        'targetMeanIoU': None,
                        'targetRecall': None,
                    },
                    'trackMetrics': None,
                    'failureReason': 'correct',
                    'review': {
                        'status': 'accepted',
                        'acceptedCandidateId': 'candidate-1',
                        'suggestedCandidateId': 'candidate-1',
                        'reasons': [],
                    },
                    'provenance': {
                        'requestId': 'req-001',
                        'command': 'analyze-frame',
                        'analysisProfileId': 'precision',
                        'developerDiagnosticsEnabled': False,
                        'runtimeVersion': 'runtime-1',
                        'restorationMode': 'mambairv2',
                        'recognizerBackend': 'hybrid',
                        'temporalEvidenceMode': 'motion-aware',
                        'sequenceReviewMode': 'strict',
                        'emittedAtMs': 1,
                    },
                    'summary': '',
                    'tags': ['aolp'],
                    'metadata': {'dataset': 'AOLP', 'split': 'subset-ac'},
                }
            ],
            'metrics': {
                'totalCases': 1,
                'exactMatchRate': 1.0,
                'top3MatchRate': 1.0,
                'meanCharacterErrorRate': 0.0,
                'acceptedRate': 1.0,
                'reviewRequiredRate': 0.0,
                'noCandidateRate': 0.0,
                'reviewBreakdown': {'accepted': 1},
                'reviewReasonBreakdown': {},
                'sourceWinCounts': {'ocr:model-a': 1},
                'meanAcceptedMargin': 1.0,
                'latencyMs': {'mean': 10.0, 'p50': 10.0, 'p95': 10.0},
                'confidenceCalibration': {'expectedCalibrationError': 0.0, 'bins': []},
                'failureBreakdown': {'correct': 1},
                'tagBreakdown': {
                    'aolp': {
                        'totalCases': 1,
                        'exactMatchRate': 1.0,
                        'top3MatchRate': 1.0,
                        'meanCharacterErrorRate': 0.0,
                        'acceptedRate': 1.0,
                        'reviewRequiredRate': 0.0,
                        'noCandidateRate': 0.0,
                        'meanLatencyMs': 10.0,
                        'meanAcceptedMargin': 1.0,
                        'meanPlateIoU': 1.0,
                        'plateLocalizationRecall': 1.0,
                        'meanTargetIoU': None,
                        'targetLocalizationRecall': None,
                        'trackMajorityExactMatchRate': None,
                        'meanPredictionSwitchCount': None,
                        'meanSampleExactMatchRate': None,
                        'meanTimeToFirstCorrectMs': None,
                    }
                },
                'datasetBreakdown': {
                    'AOLP': {
                        'totalCases': 1,
                        'exactMatchRate': 1.0,
                        'top3MatchRate': 1.0,
                        'meanCharacterErrorRate': 0.0,
                        'acceptedRate': 1.0,
                        'reviewRequiredRate': 0.0,
                        'noCandidateRate': 0.0,
                        'meanLatencyMs': 10.0,
                        'meanAcceptedMargin': 1.0,
                        'meanPlateIoU': 1.0,
                        'plateLocalizationRecall': 1.0,
                        'meanTargetIoU': None,
                        'targetLocalizationRecall': None,
                        'trackMajorityExactMatchRate': None,
                        'meanPredictionSwitchCount': None,
                        'meanSampleExactMatchRate': None,
                        'meanTimeToFirstCorrectMs': None,
                    }
                },
                'splitBreakdown': {
                    'subset-ac': {
                        'totalCases': 1,
                        'exactMatchRate': 1.0,
                        'top3MatchRate': 1.0,
                        'meanCharacterErrorRate': 0.0,
                        'acceptedRate': 1.0,
                        'reviewRequiredRate': 0.0,
                        'noCandidateRate': 0.0,
                        'meanLatencyMs': 10.0,
                        'meanAcceptedMargin': 1.0,
                        'meanPlateIoU': 1.0,
                        'plateLocalizationRecall': 1.0,
                        'meanTargetIoU': None,
                        'targetLocalizationRecall': None,
                        'trackMajorityExactMatchRate': None,
                        'meanPredictionSwitchCount': None,
                        'meanSampleExactMatchRate': None,
                        'meanTimeToFirstCorrectMs': None,
                    }
                },
            },
            'runtime': {'status': 'ready'},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact_paths = write_run_artifacts(
                suite_payload,
                runtime_result,
                'run-001',
                run_root=root / 'runs',
                report_root=root / 'reports',
            )
            result_json = Path(artifact_paths['resultJson'])
            self.assertTrue(result_json.exists())
            self.assertTrue(Path(artifact_paths['analysisJson']).exists())
            self.assertTrue(Path(artifact_paths['analysisMarkdown']).exists())
            self.assertTrue(Path(artifact_paths['suiteRegistryJson']).exists())
            self.assertTrue(Path(artifact_paths['runLedgerJson']).exists())
            self.assertTrue(Path(artifact_paths['evaluationJson']).exists())
            self.assertTrue(Path(artifact_paths['evaluationMarkdown']).exists())
            payload = json.loads(result_json.read_text(encoding='utf-8'))
            self.assertEqual(payload['runId'], 'run-001')
            self.assertEqual(payload['suite']['suiteId'], 'bundle-suite')
            self.assertEqual(payload['result']['cases'][0]['provenance']['analysisProfileId'], 'precision')
            self.assertEqual(payload['result']['cases'][0]['provenance']['recognizerBackend'], 'hybrid')
            run_ledger = json.loads(Path(artifact_paths['runLedgerJson']).read_text(encoding='utf-8'))
            self.assertEqual(run_ledger['caseCount'], 1)
            self.assertEqual(run_ledger['completedCaseCount'], 1)

    def test_inspect_suite_payload_reports_missing_sources_and_datasets(self) -> None:
        payload = {
            'schemaVersion': 1,
            'suiteId': 'doctor-suite',
            'title': 'Doctor Suite',
            'cases': [
                {
                    'id': 'case-001',
                    'mode': 'frame',
                    'sourcePath': 'C:/tmp/existing.jpg',
                    'timeMs': 100,
                    'expectedText': 'AAA1111',
                    'tags': ['local-dataset', 'aolp'],
                    'metadata': {'dataset': 'AOLP', 'category': 'blur'},
                },
                {
                    'id': 'case-002',
                    'mode': 'frame',
                    'sourcePath': 'C:/tmp/missing.jpg',
                    'timeMs': 200,
                    'expectedText': 'BBB2222',
                    'tags': ['local-dataset', 'ufpr-alpr'],
                    'metadata': {'dataset': 'UFPR-ALPR', 'category': 'tracking'},
                },
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            existing = root / 'existing.jpg'
            existing.write_bytes(b'test')
            payload['cases'][0]['sourcePath'] = str(existing)
            payload['cases'][1]['sourcePath'] = str(root / 'missing.jpg')

            summary = inspect_suite_payload(payload)

        self.assertEqual(summary['datasets'], {'AOLP': 1, 'UFPR-ALPR': 1})
        self.assertEqual(summary['splits'], {'unknown': 2})
        self.assertEqual(summary['categories'], {'blur': 1, 'tracking': 1})
        self.assertEqual(summary['missingSourcePathCount'], 1)
        self.assertEqual(summary['validationCounts'], {'blocked': 1, 'warning': 1})
        self.assertFalse(summary['readyToRun'])

    def test_build_suite_registry_materializes_case_content_and_source_integrity(self) -> None:
        payload = {
            'schemaVersion': 1,
            'suiteId': 'registry-suite',
            'analysisProfileId': 'precision',
            'cases': [
                {
                    'id': 'case-001',
                    'mode': 'frame',
                    'sourcePath': 'frame.jpg',
                    'timeMs': 150,
                    'expectedText': 'ABC1234',
                    'metadata': {'dataset': 'AOLP', 'split': 'subset-ac', 'category': 'blur'},
                },
                {
                    'id': 'case-002',
                    'mode': 'interval',
                    'sourcePath': 'missing.mp4',
                    'expectedText': 'BBB2222',
                    'anchorTimeMs': 1000,
                    'interval': {'startMs': 900, 'endMs': 1400},
                    'selectedTargetBox': {'x': 0.1, 'y': 0.2, 'width': 0.3, 'height': 0.2},
                    'metadata': {'dataset': 'UFPR-ALPR'},
                },
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'frame.jpg').write_bytes(b'frame-data')
            registry = build_suite_registry(payload, base_dir=root)
            summary = summarize_suite_registry(registry)

        self.assertEqual(len(registry.cases), 2)
        self.assertNotEqual(registry.cases[0].content_id, registry.cases[1].content_id)
        self.assertEqual(summary['sourceIntegrity']['missingSourceCount'], 1)
        self.assertEqual(summary['sourceIntegrity']['hashedSourceCount'], 1)
        self.assertEqual(summary['validationCounts'], {'blocked': 1, 'ready': 1})

    def test_build_run_evaluation_emits_hierarchical_attribution_and_registry_context(self) -> None:
        suite_payload = {
            'schemaVersion': 1,
            'suiteId': 'evaluation-suite',
            'cases': [
                {
                    'id': 'case-001',
                    'mode': 'frame',
                    'sourcePath': 'frame.jpg',
                    'timeMs': 100,
                    'expectedText': 'AAA1111',
                    'metadata': {'dataset': 'AOLP', 'split': 'subset-ac', 'category': 'blur'},
                },
                {
                    'id': 'case-002',
                    'mode': 'interval',
                    'sourcePath': 'track.mp4',
                    'expectedText': 'BBB2222',
                    'metadata': {'dataset': 'UFPR-ALPR', 'split': 'testing', 'category': 'tracking'},
                },
            ],
        }
        bundle = {
            'runId': 'run-eval',
            'generatedAt': '2026-05-17T00:00:00Z',
            'suite': {'suiteId': 'evaluation-suite', 'title': 'Evaluation Suite', 'caseCount': 2},
            'result': {
                'summary': '2 cases',
                'cases': [
                    {
                        'id': 'case-001',
                        'expectationKind': 'readable',
                        'expectedText': 'AAA1111',
                        'bestText': 'AAA1111',
                        'exactMatch': True,
                        'failureReason': 'correct',
                        'acceptedCandidateId': 'candidate-1',
                        'review': {
                            'status': 'accepted',
                            'acceptedCandidateId': 'candidate-1',
                            'suggestedCandidateId': 'candidate-1',
                            'reasons': [],
                        },
                        'latencyMs': 10.0,
                        'characterErrorRate': 0.0,
                        'metadata': {'dataset': 'AOLP', 'split': 'subset-ac', 'category': 'blur'},
                    },
                    {
                        'id': 'case-002',
                        'expectationKind': 'readable',
                        'expectedText': 'BBB2222',
                        'bestText': 'BBC2222',
                        'exactMatch': False,
                        'failureReason': 'fusion-unstable',
                        'acceptedCandidateId': None,
                        'review': {
                            'status': 'review-required',
                            'acceptedCandidateId': None,
                            'suggestedCandidateId': 'candidate-2',
                            'reasons': ['low-margin'],
                        },
                        'latencyMs': 30.0,
                        'characterErrorRate': 0.2,
                        'metadata': {'dataset': 'UFPR-ALPR', 'split': 'testing', 'category': 'tracking'},
                    },
                ],
                'metrics': {},
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'frame.jpg').write_bytes(b'frame-data')
            (root / 'track.mp4').write_bytes(b'track-data')
            registry = build_suite_registry(suite_payload, base_dir=root)

        evaluation = build_run_evaluation(bundle, suite_registry=registry)

        self.assertEqual(evaluation['stageBreakdown'], {'correct': 1, 'temporal': 1})
        self.assertEqual(evaluation['componentBreakdown'], {'correct': 1, 'fusion': 1})
        self.assertEqual(evaluation['datasetComponentBreakdown']['UFPR-ALPR'], {'fusion': 1})
        self.assertEqual(evaluation['reviewBreakdown'], {'accepted': 1, 'review-required': 1})
        self.assertEqual(evaluation['datasetReviewBreakdown']['UFPR-ALPR'], {'review-required': 1})
        self.assertEqual(evaluation['topRegressions'][0]['id'], 'case-002')
        self.assertEqual(evaluation['registry']['suiteHash'], registry.suite_hash)

    def test_import_legacy_manifest_promotes_dominant_category(self) -> None:
        legacy_payload = {
            'cases': [
                {
                    'id': 'case-001',
                    'mode': 'frame',
                    'sourcePath': 'C:/tmp/frame.jpg',
                    'timeMs': 0,
                    'expectedText': 'ABC1234',
                    'metadata': {
                        'dataset': 'AOLP',
                        'dominantCategory': 'blur',
                    },
                }
            ]
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / 'legacy.json'
            manifest_path.write_text(json.dumps(legacy_payload), encoding='utf-8')

            suite_payload = import_legacy_manifest(manifest_path, 'legacy-suite')

        self.assertEqual(suite_payload['cases'][0]['metadata']['category'], 'blur')

    def test_benchmark_run_preserves_runtime_review_state_in_case_results(self) -> None:
        workflow = BenchmarkRunWorkflow(
            ensure_ready=lambda: None,
            status=lambda: {'status': 'ready'},
            analyze_frame=lambda payload: {
                'candidates': [
                    {
                        'id': 'candidate-1',
                        'text': 'AAB1111',
                        'confidence': 0.91,
                        'source': 'fused',
                    }
                ],
                'acceptedCandidateId': None,
                'review': {
                    'status': 'review-required',
                    'acceptedCandidateId': None,
                    'suggestedCandidateId': 'candidate-1',
                    'reasons': ['low-margin'],
                },
                'provenance': {
                    'requestId': 'req-001',
                    'command': 'analyze-frame',
                    'analysisProfileId': 'precision',
                    'developerDiagnosticsEnabled': False,
                    'runtimeVersion': 'runtime-1',
                    'emittedAtMs': 1,
                },
                'summary': 'review needed',
                'runtime': {'status': 'ready'},
            },
            analyze_interval=lambda payload: {'candidates': [], 'summary': '', 'runtime': {'status': 'ready'}},
        )

        runtime_result = workflow.run(
            {
                'cases': [
                    {
                        'id': 'case-001',
                        'mode': 'frame',
                        'sourcePath': 'frame.jpg',
                        'timeMs': 0,
                        'expectedText': 'AAA1111',
                    }
                ]
            }
        )

        self.assertEqual(runtime_result['cases'][0]['acceptedCandidateId'], None)
        self.assertEqual(runtime_result['cases'][0]['review']['status'], 'review-required')
        self.assertEqual(runtime_result['cases'][0]['review']['suggestedCandidateId'], 'candidate-1')
        self.assertEqual(runtime_result['cases'][0]['provenance']['analysisProfileId'], 'precision')

    def test_benchmark_run_supports_unreadable_expectation_case(self) -> None:
        workflow = BenchmarkRunWorkflow(
            ensure_ready=lambda: None,
            status=lambda: {'status': 'ready'},
            analyze_frame=lambda payload: {
                'candidates': [],
                'acceptedCandidateId': None,
                'review': {
                    'status': 'no-candidate',
                    'acceptedCandidateId': None,
                    'suggestedCandidateId': None,
                    'reasons': [],
                },
                'provenance': {
                    'requestId': 'req-002',
                    'command': 'analyze-frame',
                    'analysisProfileId': 'precision',
                    'developerDiagnosticsEnabled': False,
                    'runtimeVersion': 'runtime-1',
                    'emittedAtMs': 2,
                },
                'summary': 'no read',
                'runtime': {'status': 'ready'},
            },
            analyze_interval=lambda payload: {'candidates': [], 'summary': '', 'runtime': {'status': 'ready'}},
        )

        runtime_result = workflow.run(
            {
                'cases': [
                    {
                        'id': 'case-001',
                        'mode': 'frame',
                        'sourcePath': 'frame.jpg',
                        'timeMs': 0,
                        'expectation': {'kind': 'unreadable'},
                        'metadata': {'dataset': 'LP2025', 'category': 'blur'},
                    }
                ]
            }
        )

        self.assertEqual(runtime_result['cases'][0]['expectationKind'], 'unreadable')
        self.assertIsNone(runtime_result['cases'][0]['expectedText'])
        self.assertTrue(runtime_result['cases'][0]['exactMatch'])
        self.assertTrue(runtime_result['cases'][0]['top3Match'])
        self.assertEqual(runtime_result['cases'][0]['characterErrorRate'], 0.0)
        self.assertEqual(runtime_result['cases'][0]['failureReason'], 'correct')

    def test_summarize_benchmark_results_rebuilds_metrics_from_case_results(self) -> None:
        runtime_result = summarize_benchmark_results(
            [
                {
                    'id': 'case-001',
                    'mode': 'frame',
                    'expectationKind': 'readable',
                    'expectedText': 'AAA1111',
                    'bestText': 'AAA1111',
                    'bestSource': 'ocr:model-a',
                    'allSources': ['ocr:model-a'],
                    'top3Texts': ['AAA1111'],
                    'exactMatch': True,
                    'top3Match': True,
                    'characterErrorRate': 0.0,
                    'acceptedConfidence': 0.98,
                    'acceptedMargin': 0.5,
                    'latencyMs': 12.0,
                    'localization': {'plateMeanIoU': 1.0, 'plateRecall': 1.0},
                    'trackMetrics': None,
                    'failureReason': 'correct',
                    'acceptedCandidateId': 'candidate-1',
                    'review': {
                        'status': 'accepted',
                        'acceptedCandidateId': 'candidate-1',
                        'suggestedCandidateId': 'candidate-1',
                        'reasons': [],
                    },
                    'summary': 'ok',
                    'tags': ['aolp', 'blur'],
                    'metadata': {'dataset': 'AOLP', 'split': 'subset-ac'},
                },
                {
                    'id': 'case-002',
                    'mode': 'interval',
                    'expectationKind': 'readable',
                    'expectedText': 'BBB2222',
                    'bestText': 'BBC2222',
                    'bestSource': 'fused',
                    'allSources': ['fused', 'ocr:model-b'],
                    'top3Texts': ['BBC2222', 'BBB2222'],
                    'exactMatch': False,
                    'top3Match': True,
                    'characterErrorRate': 0.143,
                    'acceptedConfidence': 0.44,
                    'acceptedMargin': 0.04,
                    'latencyMs': 24.0,
                    'localization': {'plateMeanIoU': 0.4, 'plateRecall': 0.0},
                    'trackMetrics': {
                        'majorityExactMatch': False,
                        'predictionSwitchCount': 3,
                        'sampleExactMatchRate': 0.25,
                        'timeToFirstCorrectMs': None,
                    },
                    'failureReason': 'fusion-unstable',
                    'acceptedCandidateId': None,
                    'review': {
                        'status': 'review-required',
                        'acceptedCandidateId': None,
                        'suggestedCandidateId': 'candidate-2',
                        'reasons': ['low-margin'],
                    },
                    'summary': 'retry',
                    'tags': ['ufpr-alpr', 'tracking'],
                    'metadata': {'dataset': 'UFPR-ALPR', 'split': 'testing'},
                },
            ],
            runtime_status={'status': 'ready'},
        )

        self.assertEqual(runtime_result['metrics']['totalCases'], 2)
        self.assertAlmostEqual(runtime_result['metrics']['exactMatchRate'], 0.5)
        self.assertAlmostEqual(runtime_result['metrics']['acceptedRate'], 0.5)
        self.assertAlmostEqual(runtime_result['metrics']['reviewRequiredRate'], 0.5)
        self.assertAlmostEqual(runtime_result['metrics']['noCandidateRate'], 0.0)
        self.assertEqual(runtime_result['metrics']['reviewReasonBreakdown'], {'low-margin': 1})
        self.assertEqual(runtime_result['metrics']['sourceWinCounts'], {'fused': 1, 'ocr:model-a': 1})
        self.assertEqual(runtime_result['metrics']['failureBreakdown'], {'correct': 1, 'fusion-unstable': 1})
        self.assertEqual(runtime_result['metrics']['datasetBreakdown']['AOLP']['totalCases'], 1)
        self.assertEqual(runtime_result['metrics']['datasetBreakdown']['UFPR-ALPR']['reviewRequiredRate'], 1.0)
        self.assertEqual(runtime_result['metrics']['splitBreakdown']['testing']['totalCases'], 1)

    def test_summarize_benchmark_results_builds_sequence_difficulty_breakdown(self) -> None:
        runtime_result = summarize_benchmark_results(
            [
                {
                    'id': 'case-001',
                    'mode': 'interval',
                    'expectationKind': 'readable',
                    'expectedText': 'AAA1111',
                    'bestText': 'AAA1111',
                    'bestSource': 'fused',
                    'allSources': ['fused'],
                    'top3Texts': ['AAA1111'],
                    'exactMatch': True,
                    'top3Match': True,
                    'characterErrorRate': 0.0,
                    'acceptedConfidence': 0.94,
                    'acceptedMargin': 0.32,
                    'latencyMs': 18.0,
                    'localization': {'plateMeanIoU': 0.9, 'plateRecall': 1.0, 'targetMeanIoU': 0.85, 'targetRecall': 1.0},
                    'trackMetrics': {
                        'majorityExactMatch': True,
                        'predictionSwitchCount': 0,
                        'sampleExactMatchRate': 1.0,
                        'timeToFirstCorrectMs': 100,
                    },
                    'tracking': {
                        'trackingTier': 'full',
                        'coverageRatio': 0.96,
                        'trackedFrameCount': 8,
                    },
                    'sequence': {
                        'sequenceTier': 'stable',
                        'dominantText': 'AAA1111',
                        'persistenceRatio': 0.9,
                        'supportFrameCount': 6,
                        'sampleCount': 6,
                        'supportFrameGapCount': 0,
                        'predictionSwitchCount': 0,
                        'characterConsistency': [0.92, 0.93],
                        'characterConsistencyMean': 0.925,
                    },
                    'failureReason': 'correct',
                    'acceptedCandidateId': 'candidate-1',
                    'review': {'status': 'accepted', 'acceptedCandidateId': 'candidate-1', 'suggestedCandidateId': 'candidate-1', 'reasons': []},
                    'summary': 'stable interval',
                    'tags': ['ufpr-alpr'],
                    'metadata': {'dataset': 'UFPR-ALPR', 'split': 'testing', 'category': 'tracking'},
                },
                {
                    'id': 'case-002',
                    'mode': 'interval',
                    'expectationKind': 'readable',
                    'expectedText': 'BBB2222',
                    'bestText': 'BBC2222',
                    'bestSource': 'fused',
                    'allSources': ['fused'],
                    'top3Texts': ['BBC2222'],
                    'exactMatch': False,
                    'top3Match': False,
                    'characterErrorRate': 0.2,
                    'acceptedConfidence': 0.4,
                    'acceptedMargin': 0.04,
                    'latencyMs': 25.0,
                    'localization': {'plateMeanIoU': 0.42, 'plateRecall': 0.0, 'targetMeanIoU': 0.4, 'targetRecall': 0.0},
                    'trackMetrics': {
                        'majorityExactMatch': False,
                        'predictionSwitchCount': 2,
                        'sampleExactMatchRate': 0.25,
                        'timeToFirstCorrectMs': None,
                    },
                    'tracking': {
                        'trackingTier': 'detection-fallback',
                        'coverageRatio': 0.52,
                        'trackedFrameCount': 4,
                    },
                    'sequence': {
                        'sequenceTier': 'fragmented',
                        'dominantText': 'BBC2222',
                        'persistenceRatio': 0.3,
                        'supportFrameCount': 2,
                        'sampleCount': 6,
                        'supportFrameGapCount': 2,
                        'predictionSwitchCount': 2,
                        'characterConsistency': [0.55, 0.58],
                        'characterConsistencyMean': 0.565,
                    },
                    'failureReason': 'fusion-unstable',
                    'acceptedCandidateId': None,
                    'review': {'status': 'review-required', 'acceptedCandidateId': None, 'suggestedCandidateId': 'candidate-2', 'reasons': ['low-margin']},
                    'summary': 'fragmented interval',
                    'tags': ['ufpr-alpr'],
                    'metadata': {'dataset': 'UFPR-ALPR', 'split': 'testing', 'category': 'tracking'},
                },
            ],
            runtime_status={'status': 'ready'},
        )

        self.assertEqual(runtime_result['metrics']['sequenceTierBreakdown'], {'fragmented': 1, 'stable': 1})
        self.assertAlmostEqual(runtime_result['metrics']['meanSequencePersistence'], 0.6)
        self.assertAlmostEqual(runtime_result['metrics']['meanSequenceGapCount'], 1.0)
        self.assertAlmostEqual(runtime_result['metrics']['meanPredictionSwitchCount'], 1.0)
        self.assertAlmostEqual(runtime_result['metrics']['meanSampleExactMatchRate'], 0.625)
        self.assertAlmostEqual(runtime_result['metrics']['meanCharacterConsistencyMean'], 0.745)
        self.assertEqual(runtime_result['metrics']['difficultyBreakdown']['trackingTier']['detection-fallback']['totalCases'], 1)
        self.assertEqual(runtime_result['metrics']['difficultyBreakdown']['sequenceTier']['fragmented']['totalCases'], 1)
        self.assertAlmostEqual(runtime_result['metrics']['difficultyBreakdown']['sequenceTier']['fragmented']['reviewRequiredRate'], 1.0)

    def test_interval_localization_matches_each_ground_truth_frame_once(self) -> None:
        localization = _evaluate_localization(
            {
                'groundTruthFrames': [
                    {
                        'timeMs': 1000,
                        'targetBox': {'x': 0.1, 'y': 0.2, 'width': 0.2, 'height': 0.2},
                    }
                ],
                'sampleEveryMs': 120,
            },
            {
                'samples': [
                    {
                        'timeMs': 980,
                        'targetBox': {'x': 0.1, 'y': 0.2, 'width': 0.2, 'height': 0.2},
                    },
                    {
                        'timeMs': 1020,
                        'targetBox': {'x': 0.1, 'y': 0.2, 'width': 0.2, 'height': 0.2},
                    },
                ],
            },
        )

        self.assertEqual(localization['groundTruthFrameCount'], 1)
        self.assertEqual(localization['matchedFrameCount'], 1)
        self.assertEqual(localization['targetRecall'], 1.0)

    def test_interval_anchor_localization_falls_back_to_interval_samples_and_analysis_track(self) -> None:
        localization = _evaluate_localization(
            {
                'mode': 'interval',
                'anchorTimeMs': 1000,
                'sampleEveryMs': 120,
                'selectedTargetBox': {'x': 0.1, 'y': 0.2, 'width': 0.2, 'height': 0.2},
            },
            {
                'samples': [
                    {
                        'timeMs': 980,
                        'targetBox': {'x': 0.1, 'y': 0.2, 'width': 0.2, 'height': 0.2},
                    },
                ],
                'analysisTrack': {
                    'id': 'track-1',
                    'frames': [
                        {
                            'id': 'track-frame-1',
                            'timeMs': 1010,
                            'box': {'x': 0.1, 'y': 0.2, 'width': 0.2, 'height': 0.2},
                        }
                    ],
                },
            },
        )

        self.assertEqual(localization['groundTruthFrameCount'], 1)
        self.assertEqual(localization['matchedFrameCount'], 1)
        self.assertEqual(localization['targetRecall'], 1.0)

    def test_evaluate_runtime_result_gate_reports_failed_thresholds(self) -> None:
        runtime_result = {
            'cases': [
                {'localization': {'plateMeanIoU': 0.72}, 'review': {'status': 'accepted', 'reasons': []}},
                {'localization': {'plateMeanIoU': 0.68}, 'review': {'status': 'review-required', 'reasons': ['low-margin']}},
            ],
            'metrics': {
                'exactMatchRate': 0.75,
                'top3MatchRate': 1.0,
                'meanCharacterErrorRate': 0.05,
                'reviewRequiredRate': 0.5,
                'noCandidateRate': 0.0,
                'latencyMs': {'p95': 850.0},
            },
        }

        gate_result = evaluate_runtime_result_gate(runtime_result, {
            'minExactRate': 0.8,
            'minTop3Rate': 0.95,
            'maxMeanCer': 0.1,
            'maxReviewRequiredRate': 0.25,
            'maxNoCandidateRate': 0.1,
            'minPlateIou': 0.75,
            'maxP95LatencyMs': 500.0,
        })

        self.assertFalse(gate_result['passed'])
        failed_metrics = {check['metric'] for check in gate_result['checks'] if not check['passed']}
        self.assertEqual(failed_metrics, {'exactMatchRate', 'reviewRequiredRate', 'meanPlateIoU', 'p95LatencyMs'})

    def test_build_run_analysis_groups_failure_sources_by_dataset(self) -> None:
        bundle = {
            'runId': 'run-002',
            'suite': {
                'suiteId': 'dataset-suite',
                'title': 'Dataset Suite',
                'caseCount': 3,
            },
            'result': {
                'summary': '3 cases',
                'cases': [
                    {
                        'id': 'case-001',
                        'exactMatch': True,
                        'failureReason': 'correct',
                        'review': {'status': 'accepted', 'reasons': []},
                        'provenance': {'analysisProfileId': 'balanced'},
                        'metadata': {'dataset': 'AOLP', 'split': 'subset-ac', 'dominantCategory': 'blur'},
                    },
                    {
                        'id': 'case-002',
                        'exactMatch': False,
                        'failureReason': 'plate-localization-missed',
                        'review': {'status': 'review-required', 'reasons': ['low-confidence']},
                        'provenance': {'analysisProfileId': 'balanced'},
                        'metadata': {'dataset': 'AOLP', 'split': 'subset-le', 'dominantCategory': 'small-plate'},
                    },
                    {
                        'id': 'case-003',
                        'exactMatch': False,
                        'failureReason': 'fusion-unstable',
                        'review': {'status': 'review-required', 'reasons': ['fusion-unstable']},
                        'provenance': {'analysisProfileId': 'balanced'},
                        'metadata': {'dataset': 'UFPR-ALPR', 'split': 'testing', 'dominantCategory': 'angle'},
                    },
                ],
            },
        }

        analysis = build_run_analysis(bundle)

        self.assertEqual(analysis['failureSourceBreakdown'], {'correct': 1, 'localization': 1, 'tracking': 1})
        self.assertEqual(analysis['datasetBreakdown']['AOLP']['cases'], 2)
        self.assertEqual(analysis['datasetBreakdown']['AOLP']['failureSources'], {'correct': 1, 'localization': 1})
        self.assertEqual(analysis['focusBreakdown']['movingCameraReliability']['failureSources'], {'tracking': 1})

    def test_build_run_analysis_adds_tracking_and_sequence_difficulty_breakdown(self) -> None:
        bundle = {
            'runId': 'run-003',
            'suite': {'suiteId': 'difficulty-suite', 'title': 'Difficulty Suite', 'caseCount': 2},
            'result': {
                'summary': '2 cases',
                'cases': [
                    {
                        'id': 'case-001',
                        'exactMatch': True,
                        'failureReason': 'correct',
                        'review': {'status': 'accepted', 'reasons': []},
                        'tracking': {'trackingTier': 'full'},
                        'sequence': {'sequenceTier': 'stable'},
                        'metadata': {'dataset': 'UFPR-ALPR', 'category': 'tracking'},
                    },
                    {
                        'id': 'case-002',
                        'exactMatch': False,
                        'failureReason': 'fusion-unstable',
                        'review': {'status': 'review-required', 'reasons': ['low-margin']},
                        'tracking': {'trackingTier': 'detection-fallback'},
                        'sequence': {'sequenceTier': 'fragmented'},
                        'metadata': {'dataset': 'UFPR-ALPR', 'category': 'tracking'},
                    },
                ],
            },
        }

        analysis = build_run_analysis(bundle)

        self.assertEqual(analysis['difficultyBreakdown']['trackingTier']['detection-fallback']['cases'], 1)
        self.assertEqual(analysis['difficultyBreakdown']['sequenceTier']['fragmented']['failureSources'], {'tracking': 1})
        self.assertEqual(analysis['difficultyBreakdown']['reviewStatus']['review-required']['cases'], 1)
        self.assertEqual(analysis['focusBreakdown']['fragmentedSequence']['cases'], 1)

    def test_apply_analysis_profile_to_suite_overrides_each_case(self) -> None:
        suite_payload = {
            'suiteId': 'profile-suite',
            'analysisProfileId': 'balanced',
            'cases': [
                {'id': 'case-001', 'analysisProfileId': 'balanced'},
                {'id': 'case-002'},
            ],
        }

        updated = apply_analysis_profile_to_suite(suite_payload, 'precision')

        self.assertEqual(updated['analysisProfileId'], 'precision')
        self.assertEqual(updated['cases'][0]['analysisProfileId'], 'precision')
        self.assertEqual(updated['cases'][1]['analysisProfileId'], 'precision')
        self.assertEqual(suite_payload['analysisProfileId'], 'balanced')

    def test_build_profile_sweep_payload_preserves_profile_rows(self) -> None:
        comparison = build_profile_sweep_payload('cmp-001', {'suiteId': 'suite-001', 'title': 'Suite 001'}, [
            {'profileId': 'balanced', 'exactMatchRate': 1.0},
            {'profileId': 'precision', 'exactMatchRate': 0.9},
        ])

        self.assertEqual(comparison['comparisonId'], 'cmp-001')
        self.assertEqual([row['profileId'] for row in comparison['profiles']], ['balanced', 'precision'])


if __name__ == '__main__':
    unittest.main()
