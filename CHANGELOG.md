# Changelog

All notable changes to **AllowJarsTool** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Component versions**
>
> | Component | Version |
> |---|---|
> | Tool release | `1.0.0` |
> | Export JSON `schema_version` | `1.0` |
> | Artifact Allowlist API | `2.1` |

---

## [Unreleased]

### Planned / ideas
- Optional restore of volume ownership & grants during import (behind an explicit,
  off-by-default flag).
- `schema_version` validation in the import notebook with a clear mismatch error.
- Databricks Asset Bundle (DAB) job definitions for scheduled exports.
- CI check that runs an export dry-run against a test metastore.

---

## [1.0.0] - 2026-09-23

Initial release.

### Added
- **`notebooks/_common.py`** — shared REST helpers used via `%run ./_common`:
  - `get_allowlist` / `set_allowlist` → `GET` / `PUT`
    `/api/2.1/unity-catalog/artifact-allowlists/{artifact_type}`.
  - `get_volume_info`, `get_volume_grants`, `parse_volume_path`,
    `get_current_metastore`, plus small utilities.
  - Input validation for `artifact_type` and `match_type` enums.
- **`notebooks/01_export_allowlist.py` (Part A — Export)**:
  - Reads the allowlist for `LIBRARY_JAR`, `INIT_SCRIPT`, `LIBRARY_MAVEN`.
  - Enriches every referenced `/Volumes/...` path with volume metadata, owner,
    and permissions; maven coordinates are excluded from volume resolution.
  - Writes `allowlist_export_<timestamp>.json` and a stable
    `allowlist_export_latest.json`; returns the path via `dbutils.notebook.exit`.
  - Widgets: `artifact_types`, `output_volume_path`, `enrich_volumes`.
- **`notebooks/02_import_allowlist.py` (Part B — Import)**:
  - Loads an export JSON and applies it with `PUT`.
  - `merge` mode (union with the live allowlist) and `replace` mode
    (JSON authoritative), plus a `dry_run` preview.
  - Case-insensitive de-duplication of matchers by `(artifact, match_type)`.
  - Widgets: `input_json_path`, `artifact_types`, `import_mode`, `dry_run`.
- **Export document** carries `export_metadata.schema_version = "1.0"`.
- `README.md`, `.gitignore`.

### Tested
- End-to-end on `fevm-shared-sandbox-eastus`: real export across all three
  artifact types with volume enrichment (owner/permissions), and an import
  dry-run (merge) — both succeeded. Graceful handling verified for inaccessible
  volumes and for identities lacking `MANAGE ALLOWLIST`.

### Security
- No credentials in code — notebooks use `WorkspaceClient()` runtime auth.
- `.gitignore` excludes `.databrickscfg`, `.env`, `*.token`, `*.pat`, and the
  local `exports/` output folder.

[Unreleased]: https://github.com/vivekravichandiran/AllowJarsTool/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/vivekravichandiran/AllowJarsTool/releases/tag/v1.0.0
