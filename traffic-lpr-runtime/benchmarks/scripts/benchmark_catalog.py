from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DatasetSourcePolicy:
    dataset_id: str
    display_name: str
    source_kind: str
    retention_class: str
    root_candidates: tuple[Path, ...] = ()
    protected_paths: tuple[Path, ...] = ()
    notes: str = ''

    def resolve_root(self, override: Path | None = None) -> Path | None:
        if override is not None:
            return override.resolve()
        for candidate in self.root_candidates:
            if candidate.exists():
                return candidate.resolve()
        if self.root_candidates:
            return self.root_candidates[0].resolve()
        return None

    def to_payload(self) -> dict[str, object]:
        unique_root_candidates = list(dict.fromkeys(str(path.resolve()) for path in self.root_candidates))
        unique_protected_paths = list(dict.fromkeys(str(path.resolve()) for path in self.protected_paths))
        return {
            'datasetId': self.dataset_id,
            'displayName': self.display_name,
            'sourceKind': self.source_kind,
            'retentionClass': self.retention_class,
            'rootCandidates': unique_root_candidates,
            'protectedPaths': unique_protected_paths,
            'notes': self.notes,
        }


@dataclass(frozen=True, slots=True)
class OfficialSuitePolicy:
    suite_id: str
    display_name: str
    source_ids: tuple[str, ...]
    modes: tuple[str, ...]
    manifest_hint: str | None
    notes: str = ''

    def to_payload(self) -> dict[str, object]:
        return {
            'suiteId': self.suite_id,
            'displayName': self.display_name,
            'sourceIds': list(self.source_ids),
            'modes': list(self.modes),
            'manifestHint': self.manifest_hint,
            'notes': self.notes,
        }


def build_dataset_source_catalog(repo_root: Path) -> dict[str, DatasetSourcePolicy]:
    dataset_root = repo_root / 'datasets'
    return {
        'aolp': DatasetSourcePolicy(
            dataset_id='aolp',
            display_name='AOLP',
            source_kind='local-dataset',
            retention_class='materialize-on-demand',
            root_candidates=(dataset_root / 'AOLP', dataset_root / 'aolp'),
            protected_paths=(dataset_root / 'AOLP.zip',),
            notes='Keep the archive; extracted subsets only need to stay resident if an official suite still depends on them.',
        ),
        'ufpr-alpr': DatasetSourcePolicy(
            dataset_id='ufpr-alpr',
            display_name='UFPR-ALPR',
            source_kind='local-dataset',
            retention_class='materialize-on-demand',
            root_candidates=(dataset_root / 'UFPR-ALPR dataset', dataset_root / 'ufpr-alpr'),
            protected_paths=(dataset_root / 'yj4Iu2-UFPR-ALPR.zip',),
            notes='The workspace still has a legacy extracted folder name; use the catalog instead of hard-coding a single path.',
        ),
        'lp2025': DatasetSourcePolicy(
            dataset_id='lp2025',
            display_name='LP2025',
            source_kind='local-dataset',
            retention_class='materialize-on-demand',
            root_candidates=(dataset_root / 'LP2025',),
            protected_paths=(dataset_root / 'LP2025.zip',),
            notes='Readable and unreadable cases share the same protected archive; materialize only the slices needed by official suites.',
        ),
        'local-dashcam': DatasetSourcePolicy(
            dataset_id='local-dashcam',
            display_name='Local Dashcam Test Media',
            source_kind='local-test-media',
            retention_class='protected-active-media',
            root_candidates=(dataset_root / 'dev-videos',),
            protected_paths=(dataset_root / 'dev-videos' / '行車紀錄.mp4',),
            notes='This is active test media, not a benchmark dataset. Do not prune it while the local dashcam suites still reference it.',
        ),
        'ccpd': DatasetSourcePolicy(
            dataset_id='ccpd',
            display_name='CCPD subset 30k',
            source_kind='public-remote',
            retention_class='runtime-cache-only',
            notes='Downloaded on demand into the benchmark runtime cache; nothing under datasets/ should be retained for it.',
        ),
        'uc3m-lp': DatasetSourcePolicy(
            dataset_id='uc3m-lp',
            display_name='UC3M-LP',
            source_kind='public-remote',
            retention_class='runtime-cache-only',
            notes='Remote archive access stays outside datasets/ and should only materialize into .runtime/cache/benchmark.',
        ),
    }


def build_official_suite_catalog(repo_root: Path) -> tuple[OfficialSuitePolicy, ...]:
    runtime_manifest_root = repo_root / 'traffic-lpr-runtime' / 'benchmarks' / 'manifests'
    return (
        OfficialSuitePolicy(
            suite_id='local-dashcam-tracking',
            display_name='Local Dashcam Tracking Gate',
            source_ids=('local-dashcam',),
            modes=('interval',),
            manifest_hint=str((runtime_manifest_root / 'templates' / 'local-dashcam-nce9762.json').resolve()),
            notes='Protect the local test media until this suite is retired or moved to a new source root.',
        ),
        OfficialSuitePolicy(
            suite_id='lp2025-readable-ocr',
            display_name='LP2025 Readable OCR Gate',
            source_ids=('lp2025',),
            modes=('frame',),
            manifest_hint=None,
            notes='Readable LP2025 is the first official local OCR slice; unreadable cases remain a later schema extension.',
        ),
        OfficialSuitePolicy(
            suite_id='aolp-readable-ocr',
            display_name='AOLP OCR and Localization Gate',
            source_ids=('aolp',),
            modes=('frame',),
            manifest_hint=None,
            notes='Taiwan OCR baseline sourced from the protected AOLP archive or its temporary materialization.',
        ),
        OfficialSuitePolicy(
            suite_id='ufpr-moving-camera',
            display_name='UFPR Moving Camera Reliability Gate',
            source_ids=('ufpr-alpr',),
            modes=('interval',),
            manifest_hint=None,
            notes='Track-video materialization belongs in .runtime/cache/benchmark, not under datasets/.',
        ),
        OfficialSuitePolicy(
            suite_id='public-multisource-comparison',
            display_name='Public Multi-Source Comparison Gate',
            source_ids=('ccpd', 'uc3m-lp'),
            modes=('frame',),
            manifest_hint=None,
            notes='Compares the public remote OCR slices without requiring any checked-in dataset roots under datasets/.',
        ),
        OfficialSuitePolicy(
            suite_id='ccpd-readable-ocr',
            display_name='CCPD Readable OCR Gate',
            source_ids=('ccpd',),
            modes=('frame',),
            manifest_hint=None,
            notes='Official public OCR gate backed by the cached CCPD archive, not by a checked-in dataset root.',
        ),
        OfficialSuitePolicy(
            suite_id='uc3m-readable-ocr',
            display_name='UC3M Readable OCR Gate',
            source_ids=('uc3m-lp',),
            modes=('frame',),
            manifest_hint=None,
            notes='Official public OCR gate backed by remote-range UC3M access and runtime cache materialization only.',
        ),
    )


def build_dataset_retention_report(repo_root: Path) -> dict[str, object]:
    dataset_root = repo_root / 'datasets'
    catalog = build_dataset_source_catalog(repo_root)
    official_suites = build_official_suite_catalog(repo_root)
    tracked_roots: set[Path] = set()
    protected_paths: set[Path] = set()
    materialize_on_demand: set[Path] = set()

    for policy in catalog.values():
        protected_paths.update(path.resolve() for path in policy.protected_paths)
        resolved_root = policy.resolve_root()
        if resolved_root is not None:
            tracked_roots.add(resolved_root)
            if policy.retention_class == 'materialize-on-demand':
                materialize_on_demand.add(resolved_root)

    existing_paths = sorted(path.resolve() for path in dataset_root.iterdir()) if dataset_root.exists() else []
    protected_existing = [str(path) for path in existing_paths if path in protected_paths]
    tracked_existing = [str(path) for path in existing_paths if path in tracked_roots]
    deletion_review_candidates = [
        str(path)
        for path in existing_paths
        if path.name.lower() != 'readme.md' and path not in protected_paths and path not in tracked_roots
    ]

    return {
        'datasetRoot': str(dataset_root.resolve()),
        'protectedExistingPaths': protected_existing,
        'trackedExistingRoots': tracked_existing,
        'materializeOnDemandRoots': [str(path) for path in sorted(materialize_on_demand)],
        'deletionReviewCandidates': deletion_review_candidates,
        'sourceCatalog': {
            dataset_id: policy.to_payload()
            for dataset_id, policy in sorted(catalog.items())
        },
        'officialSuites': [suite.to_payload() for suite in official_suites],
    }