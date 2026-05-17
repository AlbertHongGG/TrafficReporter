This folder exists because these schemas are shared across multiple boundaries in the repository.

- `schemas/lpr/` is the source of truth for LPR contracts used by the frontend, Rust host, and Python runtime.
- `schemas/benchmark/` is the source of truth for benchmark suites and benchmark run bundles.

Keeping shared schemas here avoids hiding cross-cutting contracts under one tool-specific folder such as `traffic-lpr-benchmark/` or one implementation-specific folder such as `src/`.