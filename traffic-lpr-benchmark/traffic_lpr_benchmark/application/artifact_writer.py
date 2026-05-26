from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..domain.models import BenchmarkRunBundle, BenchmarkSuite, format_case_expectation
from ..infrastructure.workspace import default_run_root
from .analysis_service import build_analysis_markdown, build_run_analysis
from .case_registry_service import build_suite_registry
from .evaluation_engine import build_evaluation_markdown, build_run_evaluation
from .run_ledger_service import build_run_ledger
from .validation_service import validate_run_bundle_payload
from traffic_lpr_runtime.infrastructure.runtime_layout import build_run_id


def _format_rate(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return '--'
    return f'{value * 100:.1f}%'


def _format_number(value: Any, digits: int = 3) -> str:
    if not isinstance(value, (int, float)):
        return '--'
    return f'{value:.{digits}f}'


def _safe_text(value: Any) -> str:
    return html.escape(str(value)) if value is not None else '--'


def create_run_id(suite_id: str | None = None) -> str:
    del suite_id
    return build_run_id()


def write_run_artifacts(
    suite_payload: dict[str, Any],
    runtime_result: dict[str, Any],
    run_id: str,
    run_root: Path | None = None,
    report_root: Path | None = None,
    suite_base_dir: Path | None = None,
    artifact_root: Path | None = None,
) -> dict[str, str]:
    del report_root
    resolved_run_root = (artifact_root or ((run_root or default_run_root()).resolve() / run_id / 'benchmark')).resolve()
    resolved_run_root.mkdir(parents=True, exist_ok=True)

    suite = BenchmarkSuite.from_payload(suite_payload)
    bundle = BenchmarkRunBundle(
        run_id=run_id,
        generated_at=datetime.now().astimezone().isoformat(timespec='seconds'),
        suite_id=suite.suite_id,
        suite_title=suite.title,
        suite_case_count=len(suite.cases),
        result=runtime_result,
    ).to_payload()
    validate_run_bundle_payload(bundle, source=f'run-bundle:{run_id}')

    result_path = resolved_run_root / 'result.json'
    summary_path = resolved_run_root / 'summary.md'
    analysis_json_path = resolved_run_root / 'analysis.json'
    analysis_markdown_path = resolved_run_root / 'analysis.md'
    suite_registry_path = resolved_run_root / 'suite-registry.json'
    run_ledger_path = resolved_run_root / 'run-ledger.json'
    evaluation_json_path = resolved_run_root / 'evaluation.json'
    evaluation_markdown_path = resolved_run_root / 'evaluation.md'
    report_path = resolved_run_root / 'report.html'
    suite_registry = build_suite_registry(suite_payload, base_dir=suite_base_dir)
    analysis_payload = build_run_analysis(bundle)
    run_ledger = build_run_ledger(run_id, bundle['generatedAt'], suite_registry, runtime_result)
    evaluation_payload = build_run_evaluation(bundle, suite_registry=suite_registry)

    result_path.write_text(json.dumps(bundle, indent=2), encoding='utf-8')
    summary_path.write_text(build_summary_markdown(bundle), encoding='utf-8')
    analysis_json_path.write_text(json.dumps(analysis_payload, indent=2), encoding='utf-8')
    analysis_markdown_path.write_text(build_analysis_markdown(bundle, analysis_payload), encoding='utf-8')
    suite_registry_path.write_text(json.dumps(suite_registry.to_payload(), indent=2), encoding='utf-8')
    run_ledger_path.write_text(json.dumps(run_ledger, indent=2), encoding='utf-8')
    evaluation_json_path.write_text(json.dumps(evaluation_payload, indent=2), encoding='utf-8')
    evaluation_markdown_path.write_text(build_evaluation_markdown(evaluation_payload), encoding='utf-8')
    report_html = build_report_html(bundle)
    report_path.write_text(report_html, encoding='utf-8')

    return {
        'runDir': str(resolved_run_root),
        'resultJson': str(result_path),
        'summaryMarkdown': str(summary_path),
        'analysisJson': str(analysis_json_path),
        'analysisMarkdown': str(analysis_markdown_path),
        'suiteRegistryJson': str(suite_registry_path),
        'runLedgerJson': str(run_ledger_path),
        'evaluationJson': str(evaluation_json_path),
        'evaluationMarkdown': str(evaluation_markdown_path),
        'reportHtml': str(report_path),
    }


def build_summary_markdown(bundle: dict[str, Any]) -> str:
    result = bundle.get('result') or {}
    metrics = result.get('metrics') or {}
    return '\n'.join([
        f"# {bundle.get('suite', {}).get('title') or bundle.get('suite', {}).get('suiteId')}",
        '',
        f"- Run ID: {bundle.get('runId')}",
        f"- Generated at: {bundle.get('generatedAt')}",
        f"- Summary: {result.get('summary') or '--'}",
        f"- Exact match: {_format_rate(metrics.get('exactMatchRate'))}",
        f"- Top-3 match: {_format_rate(metrics.get('top3MatchRate'))}",
        f"- Review required: {_format_rate(metrics.get('reviewRequiredRate'))}",
        f"- No candidate: {_format_rate(metrics.get('noCandidateRate'))}",
        f"- Mean CER: {_format_number(metrics.get('meanCharacterErrorRate'))}",
        f"- Mean accepted margin: {_format_number(metrics.get('meanAcceptedMargin'))}",
    ]) + '\n'


def build_report_html(bundle: dict[str, Any]) -> str:
    suite = bundle.get('suite') or {}
    result = bundle.get('result') or {}
    metrics = result.get('metrics') or {}
    cases = result.get('cases') or []

    cards = [
        ('Summary', _safe_text(result.get('summary') or '--')),
        ('Exact', _format_rate(metrics.get('exactMatchRate'))),
        ('Top-3', _format_rate(metrics.get('top3MatchRate'))),
        ('Review', _format_rate(metrics.get('reviewRequiredRate'))),
        ('No Candidate', _format_rate(metrics.get('noCandidateRate'))),
        ('Mean CER', _format_number(metrics.get('meanCharacterErrorRate'))),
        ('Mean Margin', _format_number(metrics.get('meanAcceptedMargin'))),
        ('P95 Latency', _format_number((metrics.get('latencyMs') or {}).get('p95'), 1) + ' ms'),
    ]

    card_markup = ''.join(
        f'<article class="card"><h2>{html.escape(label)}</h2><p>{value}</p></article>'
        for label, value in cards
    )

    rows = []
    for case in cases:
        localization = case.get('localization') or {}
        review = case['review']
        provenance = case['provenance']
        expected_display = format_case_expectation(str(case.get('expectationKind') or 'readable'), case.get('expectedText'))
        rows.append(
            '<tr>'
            f'<td>{_safe_text(case.get("id"))}</td>'
            f'<td>{_safe_text(case.get("mode"))}</td>'
            f'<td>{_safe_text(expected_display)}</td>'
            f'<td>{_safe_text(case.get("bestText"))}</td>'
            f'<td>{_safe_text(case.get("failureReason"))}</td>'
            f'<td>{_safe_text(review.get("status"))}</td>'
            f'<td>{_safe_text(provenance.get("analysisProfileId"))}</td>'
            f'<td>{_format_number(case.get("acceptedConfidence"), 3)}</td>'
            f'<td>{_format_number(case.get("latencyMs"), 1)}</td>'
            f'<td>{_format_number(localization.get("plateMeanIoU"), 3)}</td>'
            f'<td>{_format_number(localization.get("targetMeanIoU"), 3)}</td>'
            '</tr>'
        )

    rows_markup = ''.join(rows) or '<tr><td colspan="11">No cases.</td></tr>'
    failure_breakdown = ''.join(
        f'<li><strong>{_safe_text(name)}</strong>: {_safe_text(count)}</li>'
        for name, count in sorted((metrics.get('failureBreakdown') or {}).items())
    ) or '<li>No failures recorded.</li>'
    review_breakdown = ''.join(
        f'<li><strong>{_safe_text(name)}</strong>: {_safe_text(count)}</li>'
        for name, count in sorted((metrics.get('reviewBreakdown') or {}).items())
    ) or '<li>No review states recorded.</li>'

    return f'''<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{_safe_text(suite.get('title') or suite.get('suiteId') or 'Benchmark Report')}</title>
    <style>
      :root {{
        color-scheme: light;
        --bg: #f2efe9;
        --panel: rgba(255, 252, 246, 0.9);
        --ink: #1f1d1a;
        --muted: #675f53;
        --accent: #0c6b58;
        --border: rgba(31, 29, 26, 0.12);
      }}
      * {{ box-sizing: border-box; }}
      body {{ margin: 0; font-family: "Segoe UI", sans-serif; background: radial-gradient(circle at top, #fff8e8, var(--bg)); color: var(--ink); }}
      main {{ max-width: 1240px; margin: 0 auto; padding: 32px; }}
      h1 {{ margin: 0 0 8px; font-size: 2.2rem; }}
      .meta {{ color: var(--muted); margin-bottom: 24px; }}
      .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }}
      .card, .panel {{ background: var(--panel); border: 1px solid var(--border); border-radius: 18px; box-shadow: 0 18px 40px rgba(30, 24, 15, 0.06); }}
      .card {{ padding: 18px; }}
      .card h2 {{ margin: 0 0 10px; font-size: 0.9rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }}
      .card p {{ margin: 0; font-size: 1.4rem; line-height: 1.3; }}
      .layout {{ display: grid; grid-template-columns: 280px minmax(0, 1fr); gap: 16px; align-items: start; }}
      .panel {{ padding: 18px; }}
      table {{ width: 100%; border-collapse: collapse; font-size: 0.95rem; }}
      th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }}
      th {{ color: var(--muted); font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.06em; }}
      ul {{ margin: 0; padding-left: 18px; }}
      @media (max-width: 960px) {{
        main {{ padding: 20px; }}
        .layout {{ grid-template-columns: 1fr; }}
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>{_safe_text(suite.get('title') or suite.get('suiteId') or 'Benchmark Report')}</h1>
      <div class="meta">Run {_safe_text(bundle.get('runId'))} · Generated {_safe_text(bundle.get('generatedAt'))} · Cases {_safe_text(suite.get('caseCount'))}</div>
      <section class="cards">{card_markup}</section>
      <section class="layout">
        <aside class="panel">
          <h2>Failure Breakdown</h2>
          <ul>{failure_breakdown}</ul>
          <h2>Review Breakdown</h2>
          <ul>{review_breakdown}</ul>
        </aside>
        <section class="panel">
          <h2>Cases</h2>
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Mode</th>
                <th>Expected</th>
                <th>Best</th>
                <th>Failure</th>
                <th>Review</th>
                <th>Profile</th>
                <th>Confidence</th>
                <th>Latency ms</th>
                <th>Plate IoU</th>
                <th>Target IoU</th>
              </tr>
            </thead>
            <tbody>{rows_markup}</tbody>
          </table>
        </section>
      </section>
    </main>
  </body>
</html>
'''