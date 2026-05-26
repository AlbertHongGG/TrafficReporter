from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..application import BenchmarkCoordinator
from ..application.validation_service import ValidationError
from ..infrastructure.runtime_bridge_client import RuntimeInvokeError
from ..infrastructure.workspace import default_runtime_root, default_workspace_root


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
    import_parser.add_argument('--analysis-profile', default='precision')
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
    run_parser.add_argument('--run-id')
    run_parser.add_argument('--resume', action='store_true', help='Resume an interrupted benchmark run from its checkpoint file.')
    run_parser.add_argument('--progress-file', type=Path, help='Where to write per-case progress JSON. Defaults to the run directory.')
    run_parser.add_argument('--checkpoint-file', type=Path, help='Where to write resumable partial benchmark results. Defaults to the run directory.')
    run_parser.add_argument('--no-progress-log', action='store_true', help='Do not mirror progress updates to stderr while the runtime is executing.')
    run_parser.add_argument('--min-exact-rate', type=float)
    run_parser.add_argument('--min-top3-rate', type=float)
    run_parser.add_argument('--max-mean-cer', type=float)
    run_parser.add_argument('--max-review-required-rate', type=float)
    run_parser.add_argument('--max-no-candidate-rate', type=float)
    run_parser.add_argument('--min-plate-iou', type=float)
    run_parser.add_argument('--max-p95-latency-ms', type=float)

    sweep_parser = subparsers.add_parser('profile-sweep', help='Run the same suite across multiple analysis profiles and emit a comparison summary.')
    sweep_parser.add_argument('--suite', type=Path, required=True)
    sweep_parser.add_argument('--profiles', nargs='+', required=True)
    sweep_parser.add_argument('--comparison-id')
    sweep_parser.add_argument('--run-id-prefix')
    sweep_parser.add_argument('--runtime-root', type=Path, default=default_runtime_root())
    sweep_parser.add_argument('--python')
    sweep_parser.add_argument('--no-progress-log', action='store_true')
    sweep_parser.add_argument('--min-exact-rate', type=float)
    sweep_parser.add_argument('--min-top3-rate', type=float)
    sweep_parser.add_argument('--max-mean-cer', type=float)
    sweep_parser.add_argument('--max-review-required-rate', type=float)
    sweep_parser.add_argument('--max-no-candidate-rate', type=float)
    sweep_parser.add_argument('--min-plate-iou', type=float)
    sweep_parser.add_argument('--max-p95-latency-ms', type=float)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    coordinator = BenchmarkCoordinator()
    try:
        if args.command == 'init-workspace':
            return coordinator.init_workspace(args)
        if args.command == 'import-legacy-manifest':
            return coordinator.import_legacy_manifest(args)
        if args.command == 'validate':
            return coordinator.validate_suite(args)
        if args.command == 'doctor':
            return coordinator.doctor_suite(args)
        if args.command == 'validate-profile-catalog':
            return coordinator.validate_profile_catalog(args)
        if args.command == 'print-summary':
            return coordinator.print_summary(args)
        if args.command == 'run':
            return coordinator.run_suite(args)
        if args.command == 'profile-sweep':
            return coordinator.profile_sweep(args)
        parser.error(f'Unsupported command: {args.command}')
        return 2
    except ValidationError as error:
        print(str(error), file=sys.stderr)
        return 1
    except RuntimeInvokeError as error:
        print(str(error), file=sys.stderr)
        return 1