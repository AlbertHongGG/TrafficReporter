from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..domain.models import BenchmarkSuite
from ..infrastructure.runtime_bridge_client import run_benchmark_suite
from ..infrastructure.workspace import default_run_root, ensure_workspace
from .analysis_service import build_run_analysis
from .artifact_writer import create_run_id, write_run_artifacts
from .gate_policy import build_gate_thresholds, evaluate_runtime_result_gate, write_gate_result
from .legacy_manifest_importer import import_legacy_manifest
from .profile_comparison_service import apply_analysis_profile_to_suite, build_profile_sweep_payload, summarize_profile_run, write_profile_sweep_artifacts
from .validation_service import ValidationError, inspect_suite_payload, validate_profile_catalog_file, validate_suite_file, validate_suite_payload


class BenchmarkCoordinator:
    def init_workspace(self, args: Any) -> int:
        root = ensure_workspace(args.root)
        print(json.dumps({'workspaceRoot': str(root), 'status': 'ready'}, indent=2))
        return 0

    def import_legacy_manifest(self, args: Any) -> int:
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

    def validate_suite(self, args: Any) -> int:
        payload = validate_suite_file(args.suite)
        print(json.dumps({'suiteId': payload['suiteId'], 'cases': len(payload['cases']), 'valid': True}, indent=2))
        return 0

    def doctor_suite(self, args: Any) -> int:
        payload = validate_suite_file(args.suite)
        summary = inspect_suite_payload(payload, base_dir=args.suite.parent)
        print(json.dumps(summary, indent=2))
        return 0 if summary['readyToRun'] else 1

    def validate_profile_catalog(self, args: Any) -> int:
        payload = validate_profile_catalog_file(args.file)
        print(json.dumps({'defaultProfileId': payload['defaultProfileId'], 'profiles': len(payload['profiles']), 'valid': True}, indent=2))
        return 0

    def print_summary(self, args: Any) -> int:
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

    def run_suite(self, args: Any) -> int:
        payload = validate_suite_file(args.suite)
        ensure_workspace(runtime_root=args.runtime_root)
        run_id = args.run_id or create_run_id(payload['suiteId'])
        run_root = default_run_root(args.runtime_root).resolve()
        run_dir = (run_root / run_id / 'benchmark').resolve()
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
            run_id=run_id,
            artifact_root=run_dir,
            request_id=run_id,
            progress_path=progress_path,
            checkpoint_path=checkpoint_path,
            resume_from_checkpoint=bool(args.resume),
            progress_reporter=None if args.no_progress_log else _print_progress_update,
        )
        artifact_paths = write_run_artifacts(payload, runtime_result, run_id, suite_base_dir=args.suite.parent, artifact_root=run_dir)
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

    def profile_sweep(self, args: Any) -> int:
        suite_payload = validate_suite_file(args.suite)
        self.validate_requested_profiles(args.profiles)
        ensure_workspace(runtime_root=args.runtime_root)
        run_root = default_run_root(args.runtime_root).resolve()
        comparison_id = args.comparison_id or create_run_id(f'{suite_payload["suiteId"]}-profile-sweep')
        run_id_prefix = args.run_id_prefix or comparison_id
        comparison_dir = (run_root / comparison_id / 'benchmark').resolve()
        profiles_root = comparison_dir / 'profiles'
        thresholds = build_gate_thresholds(args)
        profile_runs: list[dict[str, Any]] = []
        gate_failed = False

        for profile_id in args.profiles:
            profile_suite = apply_analysis_profile_to_suite(suite_payload, profile_id)
            run_id = profile_id if run_id_prefix == comparison_id else f'{run_id_prefix}-{profile_id}'
            run_dir = (profiles_root / run_id).resolve()
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
                run_id=comparison_id,
                artifact_root=run_dir,
                request_id=f'{comparison_id}-{run_id}',
                progress_path=progress_path,
                checkpoint_path=checkpoint_path,
                progress_reporter=None if args.no_progress_log else _make_progress_reporter(profile_id),
            )
            artifact_paths = write_run_artifacts(profile_suite, runtime_result, run_id, suite_base_dir=args.suite.parent, artifact_root=run_dir)
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
        comparison_artifacts = write_profile_sweep_artifacts(comparison_dir, comparison_payload)
        print(json.dumps({
            'comparisonId': comparison_id,
            'suiteId': suite_payload['suiteId'],
            'profiles': profile_runs,
            'artifacts': comparison_artifacts,
        }, indent=2))
        return 2 if gate_failed else 0

    @staticmethod
    def default_profile_catalog_path() -> Path:
        return Path(__file__).resolve().parents[3] / 'src' / 'shared' / 'config' / 'lpr-analysis-profiles.json'

    def validate_requested_profiles(self, profile_ids: list[str]) -> None:
        catalog_payload = validate_profile_catalog_file(self.default_profile_catalog_path())
        valid_profile_ids = {
            str(profile.get('id'))
            for profile in catalog_payload.get('profiles') or []
            if isinstance(profile, dict)
        }
        invalid_profile_ids = [profile_id for profile_id in profile_ids if profile_id not in valid_profile_ids]
        if invalid_profile_ids:
            raise ValidationError(f'Unknown analysis profile(s): {", ".join(invalid_profile_ids)}')


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