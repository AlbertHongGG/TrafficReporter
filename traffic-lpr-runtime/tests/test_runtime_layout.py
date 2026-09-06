from __future__ import annotations

import re
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic_lpr_runtime.infrastructure.storage import RuntimeStorageLayout


class RuntimeLayoutTests(unittest.TestCase):
    def test_build_run_id_uses_local_time_and_random_suffix(self) -> None:
        layout = RuntimeStorageLayout(Path.cwd())
        run_id = layout.generate_run_id(datetime(2026, 5, 25, 19, 8, 7))

        self.assertRegex(run_id, r'^260525-190807-[0-9a-f]{8}$')

    def test_runtime_layout_resolves_repo_root_from_runtime_root(self) -> None:
        runtime_root = Path(__file__).resolve().parents[1]
        layout = RuntimeStorageLayout.from_root(runtime_root)

        self.assertEqual(layout.repo_root, runtime_root.parent)
        self.assertEqual(layout.data_root, runtime_root.parent / '.runtime')

    def test_runtime_layout_uses_repo_root_runtime_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            runtime_root = repo_root / 'traffic-lpr-runtime'
            runtime_root.mkdir()
            (runtime_root / 'pyproject.toml').write_text('[project]\nname = "traffic-lpr-runtime"\n', encoding='utf-8')

            layout = RuntimeStorageLayout.from_root(runtime_root)
            runtime_data = (repo_root / '.runtime').resolve()
            self.assertEqual(layout.data_root, runtime_data)
            self.assertEqual(layout.cache_root, runtime_data / 'cache')
            self.assertEqual(layout.run_root('260525-190807-deadbeef'), runtime_data / 'runs' / '260525-190807-deadbeef')
            self.assertEqual(
                layout.run_child('260525-190807-deadbeef', 'ai-evidence', 'clip.mp4'),
                runtime_data / 'runs' / '260525-190807-deadbeef' / 'ai-evidence' / 'clip.mp4',
            )


if __name__ == '__main__':
    unittest.main()
