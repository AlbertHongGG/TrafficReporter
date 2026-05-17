from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from legacy_import import import_legacy_manifest
from models import BenchmarkSuite
from reporting import create_run_id, write_run_artifacts
from runtime_bridge import RuntimeInvokeError, run_benchmark_suite
from validation import ValidationError, inspect_suite_payload, validate_profile_catalog_file, validate_suite_file, validate_suite_payload
from workspace import default_runtime_root, default_workspace_root, ensure_workspace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='traffic-lpr-benchmark',
        description='Independent benchmark workspace for the Traffic LPR runtime.',
    )
    subparsers = parser.add_subparsers(dest='command', required=True)

    init_parser = subparsers.add_parser('init-workspace', help='Create the independent benchmark workspace folders.')
    init_parser.add_argument('--root', type=Path, default=default_workspace_root())

    import_parser = subparsers.add_parser('import-legacy-manifest', help='Convert a legacy runtime manifest into a benchmark suite file.')
    import_parser.add_argument('--manifest', type=Path, required=True)
    import_parser.add_argument('--suite-id', required=True)
    import_parser.add_argument('--title')
    import_parser.add_argument('--analysis-profile', default='balanced')
    import_parser.add_argument('--limit', type=int)
    import_parser.add_argument('--output', type=Path, required=True)

    validate_parser = subparsers.add_parser('validate', help='Validate a benchmark suite JSON file.')
    validate_parser.add_argument('--suite', type=Path, required=True)

    doctor_parser = subparsers.add_parser('doctor', help='Inspect a validated suite for missing source files and case-mix coverage.')
    doctor_parser.add_argument('--suite', type=Path, required=True)

    validate_profiles_parser = subparsers.add_parser('validate-profile-catalog', help='Validate the shared LPR analysis profile catalog.')
    validate_profiles_parser.add_argument('--file', type=Path, required=True)

    print_parser = subparsers.add_parser('print-summary', help='Print a compact suite summary.')
    print_parser.add_argument('--suite', type=Path, required=True)

    run_parser = subparsers.add_parser('run', help='Run a validated suite through the independent Python runtime and emit reports.')
    run_parser.add_argument('--suite', type=Path, required=True)
    run_parser.add_argument('--runtime-root', type=Path, default=default_runtime_root())
    run_parser.add_argument('--python')

    return parser


def command_init_workspace(args: argparse.Namespace) -> int:
    root = ensure_workspace(args.root)
    print(json.dumps({'workspaceRoot': str(root), 'status': 'ready'}, indent=2))
    return 0


def command_import_legacy_manifest(args: argparse.Namespace) -> int:
    suite_payload = import_legacy_manifest(
        manifest_path=args.manifest,
        suite_id=args.suite_id,
        title=args.title,
        analysis_profile_id=args.analysis_profile,
        limit=args.limit,
    )
    validate_suite_payload(suite_payload, source=str(args.manifest))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(suite_payload, indent=2), encoding='utf-8')
    print(json.dumps({'suitePath': str(args.output.resolve()), 'cases': len(suite_payload['cases'])}, indent=2))
    return 0


def command_validate(args: argparse.Namespace) -> int:
    payload = validate_suite_file(args.suite)
    print(json.dumps({'suiteId': payload['suiteId'], 'cases': len(payload['cases']), 'valid': True}, indent=2))
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    payload = validate_suite_file(args.suite)
    summary = inspect_suite_payload(payload, base_dir=args.suite.parent)
    print(json.dumps(summary, indent=2))
    return 0 if summary['readyToRun'] else 1


def command_validate_profile_catalog(args: argparse.Namespace) -> int:
    payload = validate_profile_catalog_file(args.file)
    print(json.dumps({'defaultProfileId': payload['defaultProfileId'], 'profiles': len(payload['profiles']), 'valid': True}, indent=2))
    return 0


def command_print_summary(args: argparse.Namespace) -> int:
    payload = validate_suite_file(args.suite)
    suite = BenchmarkSuite.from_payload(payload)

    summary: dict[str, Any] = {
        'suiteId': suite.suite_id,
        'title': suite.title,
        'cases': len(suite.cases),
        'modes': suite.mode_counts(),
        'topTags': suite.top_tags(),
    }
    print(json.dumps(summary, indent=2))
    return 0


def command_run(args: argparse.Namespace) -> int:
    payload = validate_suite_file(args.suite)
    runtime_result = run_benchmark_suite(
        suite_payload=payload,
        runtime_root=args.runtime_root,
        python_executable=args.python,
    )
    artifact_paths = write_run_artifacts(payload, runtime_result, create_run_id(payload['suiteId']))
    print(json.dumps({
        'suiteId': payload['suiteId'],
        'summary': runtime_result.get('summary'),
        'artifacts': artifact_paths,
    }, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == 'init-workspace':
            return command_init_workspace(args)
        if args.command == 'import-legacy-manifest':
            return command_import_legacy_manifest(args)
        if args.command == 'validate':
            return command_validate(args)
        if args.command == 'doctor':
            return command_doctor(args)
        if args.command == 'validate-profile-catalog':
            return command_validate_profile_catalog(args)
        if args.command == 'print-summary':
            return command_print_summary(args)
        if args.command == 'run':
            return command_run(args)
        parser.error(f'Unsupported command: {args.command}')
        return 2
    except ValidationError as error:
        print(str(error), file=sys.stderr)
        return 1
    except RuntimeInvokeError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
