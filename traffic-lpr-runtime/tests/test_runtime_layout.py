from __future__ import annotations

import re
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.infrastructure.runtime_layout import (
    benchmark_import_root,
    benchmark_suite_root,
    build_run_id,
    cache_root,
    resolve_repo_root,
    run_child,
    run_root,
    runtime_data_root,
)


class RuntimeLayoutTests(unittest.TestCase):
    def test_build_run_id_uses_local_time_and_random_suffix(self) -> None:
        run_id = build_run_id(datetime(2026, 5, 25, 19, 8, 7))

        self.assertRegex(run_id, r'^260525-190807-[0-9a-f]{8}$')

    def test_runtime_layout_resolves_repo_root_from_runtime_root(self) -> None:
        runtime_root = Path(__file__).resolve().parents[1]

        self.assertEqual(resolve_repo_root(runtime_root), runtime_root.parent)
        self.assertEqual(runtime_data_root(runtime_root), runtime_root.parent / '.runtime')

    def test_runtime_layout_uses_repo_root_runtime_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            runtime_root = repo_root / 'traffic-lpr-runtime'
            runtime_root.mkdir()
            (runtime_root / 'pyproject.toml').write_text('[project]\nname = "traffic-lpr-runtime"\n', encoding='utf-8')

            runtime_data = (repo_root / '.runtime').resolve()
            self.assertEqual(runtime_data_root(runtime_root), runtime_data)
            self.assertEqual(cache_root(runtime_root), runtime_data / 'cache')
            self.assertEqual(benchmark_suite_root(runtime_root), runtime_data / 'cache' / 'benchmark' / 'suites')
            self.assertEqual(benchmark_import_root(runtime_root), runtime_data / 'cache' / 'benchmark' / 'imports')
            self.assertEqual(run_root(runtime_root, '260525-190807-deadbeef'), runtime_data / 'runs' / '260525-190807-deadbeef')
            self.assertEqual(
                run_child(runtime_root, '260525-190807-deadbeef', 'ai-evidence', 'clip.mp4'),
                runtime_data / 'runs' / '260525-190807-deadbeef' / 'ai-evidence' / 'clip.mp4',
            )


if __name__ == '__main__':
    unittest.main()