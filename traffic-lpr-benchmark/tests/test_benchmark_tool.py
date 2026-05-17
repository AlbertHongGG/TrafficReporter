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
from profile_sweep import apply_analysis_profile_to_suite, build_profile_sweep_payload
from reporting import write_run_artifacts
from traffic_lpr_runtime.application.benchmark_workflow import summarize_benchmark_results
from validation import ValidationError, inspect_suite_payload, validate_profile_catalog_file, validate_suite_payload


class BenchmarkToolTests(unittest.TestCase):
    def test_validate_suite_payload_accepts_valid_frame_suite(self) -> None:
        payload = {
            'schemaVersion': 1,
            'suiteId': 'frame-suite',
            'title': 'Frame Suite',
            'cases': [
                {
                    'id': 'case-001',
                    'mode': 'frame',
                    'sourcePath': 'C:/tmp/frame.jpg',
                    'timeMs': 1200,
                    'expectedText': 'ABC1234',
                    'tags': ['taiwan'],
                }
            ],
        }

        validate_suite_payload(payload)

    def test_validate_suite_payload_rejects_duplicate_case_ids(self) -> None:
        payload = {
            'schemaVersion': 1,
            'suiteId': 'duplicate-suite',
            'cases': [
                {'id': 'case-001', 'mode': 'frame', 'sourcePath': 'a', 'timeMs': 1, 'expectedText': 'AAA1111'},
                {'id': 'case-001', 'mode': 'frame', 'sourcePath': 'b', 'timeMs': 2, 'expectedText': 'BBB2222'},
            ],
        }

        with self.assertRaises(ValidationError):
            validate_suite_payload(payload)

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
                {'id': 'case-001', 'mode': 'frame', 'expectedText': 'AAA1111', 'bestText': 'AAA1111', 'localization': {}}
            ],
            'metrics': {
                'totalCases': 1,
                'exactMatchRate': 1.0,
                'top3MatchRate': 1.0,
                'meanCharacterErrorRate': 0.0,
                'meanAcceptedMargin': 1.0,
                'latencyMs': {'p95': 10.0},
                'failureBreakdown': {'correct': 1},
            },
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
            payload = json.loads(result_json.read_text(encoding='utf-8'))
            self.assertEqual(payload['runId'], 'run-001')
            self.assertEqual(payload['suite']['suiteId'], 'bundle-suite')

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
        self.assertEqual(summary['categories'], {'blur': 1, 'tracking': 1})
        self.assertEqual(summary['missingSourcePathCount'], 1)
        self.assertFalse(summary['readyToRun'])

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

    def test_summarize_benchmark_results_rebuilds_metrics_from_case_results(self) -> None:
        runtime_result = summarize_benchmark_results(
            [
                {
                    'id': 'case-001',
                    'mode': 'frame',
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
                    'summary': 'ok',
                    'tags': ['aolp', 'blur'],
                    'metadata': {'dataset': 'AOLP', 'split': 'subset-ac'},
                },
                {
                    'id': 'case-002',
                    'mode': 'interval',
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
                    'summary': 'retry',
                    'tags': ['ufpr-alpr', 'tracking'],
                    'metadata': {'dataset': 'UFPR-ALPR', 'split': 'testing'},
                },
            ],
            runtime_status={'status': 'ready'},
        )

        self.assertEqual(runtime_result['metrics']['totalCases'], 2)
        self.assertAlmostEqual(runtime_result['metrics']['exactMatchRate'], 0.5)
        self.assertEqual(runtime_result['metrics']['sourceWinCounts'], {'fused': 1, 'ocr:model-a': 1})
        self.assertEqual(runtime_result['metrics']['failureBreakdown'], {'correct': 1, 'fusion-unstable': 1})
        self.assertEqual(runtime_result['metrics']['datasetBreakdown']['AOLP']['totalCases'], 1)
        self.assertEqual(runtime_result['metrics']['splitBreakdown']['testing']['totalCases'], 1)

    def test_evaluate_runtime_result_gate_reports_failed_thresholds(self) -> None:
        runtime_result = {
            'cases': [
                {'localization': {'plateMeanIoU': 0.72}},
                {'localization': {'plateMeanIoU': 0.68}},
            ],
            'metrics': {
                'exactMatchRate': 0.75,
                'top3MatchRate': 1.0,
                'meanCharacterErrorRate': 0.05,
                'latencyMs': {'p95': 850.0},
            },
        }

        gate_result = evaluate_runtime_result_gate(runtime_result, {
            'minExactRate': 0.8,
            'minTop3Rate': 0.95,
            'maxMeanCer': 0.1,
            'minPlateIou': 0.75,
            'maxP95LatencyMs': 500.0,
        })

        self.assertFalse(gate_result['passed'])
        failed_metrics = {check['metric'] for check in gate_result['checks'] if not check['passed']}
        self.assertEqual(failed_metrics, {'exactMatchRate', 'meanPlateIoU', 'p95LatencyMs'})

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
                        'metadata': {'dataset': 'AOLP', 'split': 'subset-ac', 'dominantCategory': 'blur'},
                    },
                    {
                        'id': 'case-002',
                        'exactMatch': False,
                        'failureReason': 'plate-localization-missed',
                        'metadata': {'dataset': 'AOLP', 'split': 'subset-le', 'dominantCategory': 'small-plate'},
                    },
                    {
                        'id': 'case-003',
                        'exactMatch': False,
                        'failureReason': 'fusion-unstable',
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
