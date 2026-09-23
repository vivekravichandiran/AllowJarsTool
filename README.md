# AllowJarsTool — Databricks Metastore Artifact Allowlist Export / Import

A notebook-based utility for **Databricks metastore admins** to back up and
restore the Unity Catalog **artifact allowlist** ("allow jars"). It exports the
full allowlist — plus the referenced volumes, their owners, and permissions — to
JSON in a volume, and can re-apply that JSON to a metastore via the REST API.

Built against the
[Artifact Allowlist API](https://docs.databricks.com/api/uc-artifact-allowlists/v1/artifact-allowlist)
(`/api/2.1/unity-catalog/artifact-allowlists/{artifact_type}`).

---

## Contents

| Notebook | Purpose |
|---|---|
| [`notebooks/_common.py`](notebooks/_common.py) | Shared REST helpers (pulled in via `%run ./_common`). Not run directly. |
| [`notebooks/01_export_allowlist.py`](notebooks/01_export_allowlist.py) | **Part A – Export.** Reads the allowlist, enriches referenced volumes, writes JSON. |
| [`notebooks/02_import_allowlist.py`](notebooks/02_import_allowlist.py) | **Part B – Import.** Reads the JSON and PUTs/merges the allowlist. |

---

## What gets exported

For each configured artifact type (`LIBRARY_JAR`, `INIT_SCRIPT`, `LIBRARY_MAVEN`):

- **Allowlist matchers** — `artifact` path / maven coordinate + `match_type`,
  plus `metastore_id`, `created_by`, `created_at`.
- **Referenced volumes** — for every `/Volumes/...` artifact path: the volume
  metadata (type, storage location, comment, timestamps), its **owner**, and its
  full **permissions** (privilege assignments).
- **Context metadata** — exporting user, workspace host, metastore summary,
  export timestamp, schema version.

Maven coordinates (e.g. `com.oracle.database.jdbc:ojdbc11:23.26.1.0.0`) are
correctly **not** treated as volume paths.

### Export JSON shape

```json
{
  "export_metadata": { "exported_at": "...", "exported_by": "...", "metastore": { ... }, "schema_version": "1.0" },
  "allowlists": {
    "LIBRARY_JAR":  { "artifact_matchers": [ { "artifact": "...", "match_type": "PREFIX_MATCH" } ], "created_by": "...", "created_at": 0, "metastore_id": "..." },
    "INIT_SCRIPT":  { "...": "..." },
    "LIBRARY_MAVEN":{ "...": "..." }
  },
  "volumes": [
    { "full_name": "cat.schema.vol", "owner": "...", "volume_type": "MANAGED",
      "storage_location": "...", "permissions": [ { "principal": "...", "privileges": ["..."] } ],
      "referenced_by": ["INIT_SCRIPT:/Volumes/..."] }
  ]
}
```

---

## Prerequisites

- A Unity Catalog–enabled workspace with an assigned metastore.
- The running identity must be a **metastore admin** or hold the
  **`MANAGE ALLOWLIST`** privilege on the metastore:

  ```sql
  GRANT MANAGE ALLOWLIST ON METASTORE TO `you@example.com`;
  ```

- For **export output**: write access (`WRITE VOLUME`) to a UC volume for the JSON.
- The notebooks use `WorkspaceClient()` **runtime auth** — no tokens are stored
  in code.

---

## Usage

### Part A — Export

Open `01_export_allowlist` and set the widgets:

| Widget | Default | Description |
|---|---|---|
| `artifact_types` | `LIBRARY_JAR,INIT_SCRIPT,LIBRARY_MAVEN` | Comma-separated artifact types to export. |
| `output_volume_path` | `/Volumes/main/default/allowlist_backups` | Destination folder (a UC volume path). |
| `enrich_volumes` | `true` | Resolve owners/permissions for referenced volumes. |

Output: `allowlist_export_<timestamp>.json` plus a stable
`allowlist_export_latest.json` in the output folder. The notebook returns the
timestamped path via `dbutils.notebook.exit(...)` so it can be chained.

### Part B — Import

Open `02_import_allowlist` and set the widgets:

| Widget | Default | Description |
|---|---|---|
| `input_json_path` | `.../allowlist_export_latest.json` | The export JSON to apply. |
| `artifact_types` | `LIBRARY_JAR,INIT_SCRIPT,LIBRARY_MAVEN` | Artifact types to import. |
| `import_mode` | `merge` | `merge` (union with live allowlist) or `replace` (JSON is authoritative). |
| `dry_run` | `true` | Preview the exact PUT payload without writing. Set `false` to apply. |

> The Set API **replaces the entire allowlist** for an artifact type. `merge`
> mode reads the current allowlist first and unions it with the JSON so nothing
> existing is dropped; `replace` mode writes exactly what is in the JSON.

**Always run with `dry_run=true` first** to review the payload.

### Run headlessly (one-time job)

```bash
databricks jobs submit --json '{
  "run_name": "allowjars-export",
  "tasks": [{
    "task_key": "export",
    "notebook_task": {
      "notebook_path": "/Users/you@example.com/AllowJarsTool/01_export_allowlist",
      "base_parameters": {
        "artifact_types": "LIBRARY_JAR,INIT_SCRIPT,LIBRARY_MAVEN",
        "output_volume_path": "/Volumes/main/default/allowlist_backups",
        "enrich_volumes": "true"
      }
    }
  }]
}'
```

---

## Notes & design decisions

- **Volume owners/permissions are exported for audit/DR context but not
  re-applied on import** by design — the Artifact Allowlist API only governs the
  allowlist itself, and restoring UC grants is a separate, higher-risk operation.
  The data lives in `doc["volumes"]` if you choose to reconcile manually.
- **Graceful degradation** — if a referenced volume is inaccessible or missing,
  the export records an `info_error` / `permissions_error` for that entry and
  continues; per-artifact-type read errors are captured without failing the run.
- Every allowlist call is a plain REST request via the SDK's low-level
  `api_client.do(...)`, matching the documented endpoints exactly.

---

## Versioning

See [`CHANGELOG.md`](CHANGELOG.md). This project follows
[Semantic Versioning](https://semver.org/); the export JSON carries its own
`export_metadata.schema_version` so importers can validate compatibility.
