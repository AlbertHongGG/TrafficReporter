This folder is the single workspace root for local datasets and local evaluation media.

Recommended layout:

- `datasets/aolp/`
- `datasets/ufpr-alpr/`
- `datasets/dev-videos/`

Why this exists:

- keep large local datasets out of the repository root
- separate code from local data clearly
- give benchmark preparation scripts one stable default location

This folder is intentionally ignored by Git except for this README.