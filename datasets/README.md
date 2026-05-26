This folder is the single workspace root for local datasets and local evaluation media.

Recommended layout:

- `datasets/aolp/`
- `datasets/ufpr-alpr/`
- `datasets/dev-videos/`
- `datasets/LP2025/`

Rules:

- raw local datasets stay here instead of being scattered across the repository root
- benchmark cases must carry provenance metadata such as `dataset`, plus `category` or `dominantCategory`
- benchmark tooling may materialize immutable prepared copies into runtime-owned `.runtime/` workspaces, but the source dataset still starts here
- benchmark preparation scripts can consume `AOLP`, `UFPR-ALPR`, and `LP2025` from this root when those local folders are present
- desktop UI code must not treat arbitrary dataset paths as an implicit runtime dependency
- user-facing exports do not belong here unless they are intentionally curated evaluation inputs

Why this exists:

- keep large local datasets out of the repository root
- separate code from local data clearly
- give benchmark preparation scripts one stable default location
- keep raw datasets distinct from benchmark artifacts and runtime scratch data

See `docs/lpr-architecture-boundaries.md` for the full dataset and artifact policy.

This folder is intentionally ignored by Git except for this README.