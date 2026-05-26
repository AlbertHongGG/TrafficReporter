from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark_catalog import build_dataset_retention_report


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit dataset retention and pruning candidates without deleting any files.')
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[3], help='Repository root containing datasets/.')
    parser.add_argument('--output', type=Path, default=None, help='Optional path to write the JSON report.')
    args = parser.parse_args()

    report = build_dataset_retention_report(args.repo_root.resolve())
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding='utf-8')
    print(payload)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())