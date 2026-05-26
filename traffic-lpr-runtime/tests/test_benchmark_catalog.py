from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1] / 'benchmarks' / 'scripts'
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from benchmark_catalog import build_dataset_source_catalog, build_official_suite_catalog


class BenchmarkCatalogTests(unittest.TestCase):
    def test_catalog_resolves_existing_uppercase_and_legacy_local_roots(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        catalog = build_dataset_source_catalog(repo_root)

        self.assertEqual(catalog['aolp'].resolve_root().name, 'AOLP')
        self.assertEqual(catalog['ufpr-alpr'].resolve_root().name, 'UFPR-ALPR dataset')
        self.assertEqual(catalog['lp2025'].resolve_root().name, 'LP2025')

    def test_local_dashcam_is_protected_active_media_not_dataset(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        catalog = build_dataset_source_catalog(repo_root)

        dashcam = catalog['local-dashcam']
        self.assertEqual(dashcam.source_kind, 'local-test-media')
        self.assertEqual(dashcam.retention_class, 'protected-active-media')
        self.assertTrue(any(path.name == '行車紀錄.mp4' for path in dashcam.protected_paths))

    def test_official_suite_catalog_covers_local_dashcam_and_public_slice(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        suites = build_official_suite_catalog(repo_root)
        suite_ids = {suite.suite_id for suite in suites}

        self.assertIn('local-dashcam-tracking', suite_ids)
        self.assertIn('public-multisource-comparison', suite_ids)
        local_dashcam_suite = next(suite for suite in suites if suite.suite_id == 'local-dashcam-tracking')
        self.assertEqual(local_dashcam_suite.source_ids, ('local-dashcam',))


if __name__ == '__main__':
    unittest.main()