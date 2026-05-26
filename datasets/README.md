This folder is the single workspace root for local datasets and local evaluation media.

Recommended layout:

- `datasets/AOLP/` or `datasets/aolp/`
- `datasets/UFPR-ALPR dataset/` or `datasets/ufpr-alpr/`
- `datasets/LP2025/`
- `datasets/dev-videos/`
- protected zip archives such as `datasets/AOLP.zip`, `datasets/LP2025.zip`, and `datasets/yj4Iu2-UFPR-ALPR.zip`

Rules:

- raw local datasets stay here instead of being scattered across the repository root
- `datasets/dev-videos/` is protected local test media, not a dataset; benchmark and evidence templates may reference files inside it directly, so do not prune it as part of dataset cleanup
- benchmark cases must carry provenance metadata such as `dataset`, plus `category` or `dominantCategory`
- benchmark tooling may materialize immutable prepared copies into runtime-owned `.runtime/` workspaces, but the source dataset still starts here
- benchmark preparation scripts now resolve local dataset roots through `traffic-lpr-runtime/benchmarks/scripts/benchmark_catalog.py`, so uppercase and legacy folder aliases are allowed while the catalog converges on one canonical id
- public benchmark sources such as CCPD and UC3M-LP should stay cache-backed under `.runtime/cache/benchmark/` instead of being mirrored into `datasets/`
- prune only after checking `traffic-lpr-runtime/benchmarks/scripts/audit_dataset_retention.py`; zip archives and protected active media must survive even when extracted folders become optional
- desktop UI code must not treat arbitrary dataset paths as an implicit runtime dependency
- user-facing exports do not belong here unless they are intentionally curated evaluation inputs

Why this exists:

- keep large local datasets out of the repository root
- separate code from local data clearly
- give benchmark preparation scripts one stable default location
- keep raw datasets and protected local media distinct from benchmark artifacts and runtime scratch data

See `docs/lpr-architecture-boundaries.md` for the full dataset and artifact policy.

This folder is intentionally ignored by Git except for this README.