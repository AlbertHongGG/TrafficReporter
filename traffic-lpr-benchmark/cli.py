from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from analysis import build_run_analysis
from gate import build_gate_thresholds, evaluate_runtime_result_gate, write_gate_result
from legacy_import import import_legacy_manifest
from models import BenchmarkSuite
from profile_sweep import apply_analysis_profile_to_suite, build_profile_sweep_payload, summarize_profile_run, write_profile_sweep_artifacts
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
    workspace_root = ensure_workspace()
    run_id = args.run_id or create_run_id(payload['suiteId'])
    run_root = (workspace_root / 'runs').resolve()
    report_root = (workspace_root / 'reports').resolve()
    run_dir = run_root / run_id
    progress_path = (args.progress_file or (run_dir / 'progress.json')).resolve()
    checkpoint_path = (args.checkpoint_file or (run_dir / 'checkpoint.json')).resolve()
    if not args.resume and any(path.exists() for path in (run_dir / 'result.json', progress_path, checkpoint_path)):
        raise ValidationError(f'Run artifacts already exist for run ID {run_id}. Use --resume or choose a different --run-id.')

    run_dir.mkdir(parents=True, exist_ok=True)
    print(json.dumps({
        'runId': run_id,
        'progressFile': str(progress_path),
        'checkpointFile': str(checkpoint_path),
        'resume': bool(args.resume),
    }, indent=2), file=sys.stderr)

    runtime_result = run_benchmark_suite(
        suite_payload=payload,
        runtime_root=args.runtime_root,
        python_executable=args.python,
        progress_path=progress_path,
        checkpoint_path=checkpoint_path,
        resume_from_checkpoint=bool(args.resume),
        progress_reporter=None if args.no_progress_log else _print_progress_update,
    )
    artifact_paths = write_run_artifacts(payload, runtime_result, run_id, run_root=run_root, report_root=report_root, suite_base_dir=args.suite.parent)
    thresholds = build_gate_thresholds(args)
    gate_result = evaluate_runtime_result_gate(runtime_result, thresholds)
    gate_path = write_gate_result(run_dir / 'gate.json', gate_result) if gate_result is not None else None
    print(json.dumps({
        'suiteId': payload['suiteId'],
        'runId': run_id,
        'summary': runtime_result.get('summary'),
        'artifacts': artifact_paths,
        'progressFile': str(progress_path),
        'checkpointFile': str(checkpoint_path),
        'gate': gate_result,
        'gateFile': gate_path,
    }, indent=2))
    return 0 if gate_result is None or gate_result.get('passed') else 2


def command_profile_sweep(args: argparse.Namespace) -> int:
    suite_payload = validate_suite_file(args.suite)
    _validate_requested_profiles(args.profiles)
    workspace_root = ensure_workspace()
    run_root = (workspace_root / 'runs').resolve()
    report_root = (workspace_root / 'reports').resolve()
    comparison_id = args.comparison_id or create_run_id(f'{suite_payload["suiteId"]}-profile-sweep')
    run_id_prefix = args.run_id_prefix or comparison_id
    thresholds = build_gate_thresholds(args)
    profile_runs: list[dict[str, Any]] = []
    gate_failed = False

    for profile_id in args.profiles:
        profile_suite = apply_analysis_profile_to_suite(suite_payload, profile_id)
        run_id = f'{run_id_prefix}-{profile_id}'
        run_dir = run_root / run_id
        if (run_dir / 'result.json').exists():
            raise ValidationError(f'Run artifacts already exist for profile sweep run ID {run_id}. Choose a different --run-id-prefix or clean the existing run.')

        progress_path = run_dir / 'progress.json'
        checkpoint_path = run_dir / 'checkpoint.json'
        run_dir.mkdir(parents=True, exist_ok=True)
        print(json.dumps({
            'comparisonId': comparison_id,
            'profileId': profile_id,
            'runId': run_id,
            'progressFile': str(progress_path),
            'checkpointFile': str(checkpoint_path),
        }, indent=2), file=sys.stderr)

        runtime_result = run_benchmark_suite(
            suite_payload=profile_suite,
            runtime_root=args.runtime_root,
            python_executable=args.python,
            progress_path=progress_path,
            checkpoint_path=checkpoint_path,
            progress_reporter=None if args.no_progress_log else _make_progress_reporter(profile_id),
        )
        artifact_paths = write_run_artifacts(profile_suite, runtime_result, run_id, run_root=run_root, report_root=report_root, suite_base_dir=args.suite.parent)
        gate_result = evaluate_runtime_result_gate(runtime_result, thresholds)
        gate_path = write_gate_result(run_dir / 'gate.json', gate_result) if gate_result is not None else None
        if gate_result is not None and not gate_result.get('passed'):
            gate_failed = True

        bundle_payload = json.loads(Path(artifact_paths['resultJson']).read_text(encoding='utf-8'))
        analysis_payload = build_run_analysis(bundle_payload)
        profile_runs.append(
            summarize_profile_run(
                profile_id=profile_id,
                run_id=run_id,
                runtime_result=runtime_result,
                analysis_payload=analysis_payload,
                artifact_paths={**artifact_paths, 'gateFile': gate_path} if gate_path else artifact_paths,
                gate_result=gate_result,
            )
        )

    comparison_payload = build_profile_sweep_payload(comparison_id, suite_payload, profile_runs)
    comparison_artifacts = write_profile_sweep_artifacts(report_root, comparison_payload)
    print(json.dumps({
        'comparisonId': comparison_id,
        'suiteId': suite_payload['suiteId'],
        'profiles': profile_runs,
        'artifacts': comparison_artifacts,
    }, indent=2))
    return 2 if gate_failed else 0


def _print_progress_update(progress_payload: dict[str, Any], label: str | None = None) -> None:
    total_cases = int(progress_payload.get('totalCases') or 0)
    completed_cases = int(progress_payload.get('completedCaseCount') or 0)
    percentage = f'{(completed_cases / total_cases * 100.0):.1f}%' if total_cases else '--'
    latest_case = progress_payload.get('latestCase') if isinstance(progress_payload.get('latestCase'), dict) else {}
    latest_case_id = latest_case.get('id') if isinstance(latest_case, dict) else None
    latest_failure_reason = latest_case.get('failureReason') if isinstance(latest_case, dict) else None
    status = 'completed' if progress_payload.get('completed') else 'running'
    message = f'[progress] {completed_cases}/{total_cases} ({percentage}) status={status}'
    if label:
        message += f' profile={label}'
    if latest_case_id:
        message += f' latest={latest_case_id}'
    if latest_failure_reason:
        message += f' failure={latest_failure_reason}'
    print(message, file=sys.stderr)


def _make_progress_reporter(label: str):
    def report(progress_payload: dict[str, Any]) -> None:
        _print_progress_update(progress_payload, label=label)

    return report


def _default_profile_catalog_path() -> Path:
    return Path(__file__).resolve().parent.parent / 'src' / 'shared' / 'config' / 'lpr-analysis-profiles.json'


def _validate_requested_profiles(profile_ids: list[str]) -> None:
    catalog_payload = validate_profile_catalog_file(_default_profile_catalog_path())
    valid_profile_ids = {
        str(profile.get('id'))
        for profile in catalog_payload.get('profiles') or []
        if isinstance(profile, dict)
    }
    invalid_profile_ids = [profile_id for profile_id in profile_ids if profile_id not in valid_profile_ids]
    if invalid_profile_ids:
        raise ValidationError(f'Unknown analysis profile(s): {", ".join(invalid_profile_ids)}')


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
        if args.command == 'profile-sweep':
            return command_profile_sweep(args)
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
