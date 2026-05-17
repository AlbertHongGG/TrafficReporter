from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


TOOL_ROOT = Path(__file__).resolve().parents[1]
if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))

from legacy_import import import_legacy_manifest
from reporting import write_run_artifacts
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
        self.assertEqual(payload['defaultProfileId'], 'balanced')
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


if __name__ == '__main__':
    unittest.main()
