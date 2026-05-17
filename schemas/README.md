This folder exists because these schemas are shared across multiple boundaries in the repository.

- `schemas/lpr/` is the source of truth for LPR contracts used by the frontend, Rust host, and Python runtime.
- `schemas/benchmark/` is the source of truth for benchmark suites and benchmark run bundles.
- brokered cross-boundary changes must land here first, then regenerate checked-in language bindings as needed.
- semantic validation still lives in owning tools, but the structural contract starts here.

Keeping shared schemas here avoids hiding cross-cutting contracts under one tool-specific folder such as `traffic-lpr-benchmark/` or one implementation-specific folder such as `src/`.

See `docs/lpr-architecture-boundaries.md` for the shared contract policy and cross-layer dependency rules.