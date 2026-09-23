# Databricks notebook source
# MAGIC %md
# MAGIC # `_common` — Shared helpers for the Metastore Allow-Jars utility
# MAGIC
# MAGIC This notebook is **not run directly**. It is pulled into the Export / Import
# MAGIC notebooks via `%run ./_common` and exposes:
# MAGIC
# MAGIC | Helper | Purpose |
# MAGIC |---|---|
# MAGIC | `get_allowlist(artifact_type)` | `GET /api/2.1/unity-catalog/artifact-allowlists/{artifact_type}` |
# MAGIC | `set_allowlist(artifact_type, matchers)` | `PUT` the full allowlist (replace) |
# MAGIC | `get_volume_info(full_name)` | Volume metadata incl. **owner** |
# MAGIC | `get_volume_grants(full_name)` | Volume **permissions** (privilege assignments) |
# MAGIC | `parse_volume_path(path)` | Split a `/Volumes/...` artifact into catalog/schema/volume |
# MAGIC | `get_current_metastore()` | Current metastore summary |
# MAGIC
# MAGIC All calls go through the Databricks REST API using the notebook's own
# MAGIC credentials, exactly as documented in the
# MAGIC [Artifact Allowlist API reference](https://docs.databricks.com/api/uc-artifact-allowlists/v1/artifact-allowlist).

# COMMAND ----------

import json
import re
from datetime import datetime, timezone

from databricks.sdk import WorkspaceClient

# WorkspaceClient auto-authenticates inside a Databricks notebook.
# We only use its low-level `api_client.do(...)` so every call is a plain REST
# request against the documented endpoints (no reliance on SDK service wrappers).
w = WorkspaceClient()

# Valid values per the API docs.
VALID_ARTIFACT_TYPES = {
    "ARTIFACT_TYPE_UNSPECIFIED",
    "INIT_SCRIPT",
    "LIBRARY_JAR",
    "LIBRARY_MAVEN",
}
VALID_MATCH_TYPES = {"MATCH_TYPE_UNSPECIFIED", "PREFIX_MATCH"}

_ALLOWLIST_BASE = "/api/2.1/unity-catalog/artifact-allowlists"
_VOLUME_PATH_RE = re.compile(r"^/Volumes/([^/]+)/([^/]+)/([^/]+)(/.*)?$", re.IGNORECASE)


# COMMAND ----------

# MAGIC %md ## Artifact allowlist (GET / PUT)

# COMMAND ----------

def get_allowlist(artifact_type: str) -> dict:
    """GET the artifact allowlist for a given artifact type.

    Returns the ArtifactAllowlistInfo object:
        {artifact_matchers, metastore_id, created_by, created_at}
    """
    artifact_type = artifact_type.strip().upper()
    if artifact_type not in VALID_ARTIFACT_TYPES:
        raise ValueError(
            f"Invalid artifact_type '{artifact_type}'. Expected one of {sorted(VALID_ARTIFACT_TYPES)}"
        )
    resp = w.api_client.do("GET", f"{_ALLOWLIST_BASE}/{artifact_type}")
    # Normalise so downstream code can rely on the key always existing.
    resp.setdefault("artifact_matchers", [])
    return resp


def set_allowlist(artifact_type: str, matchers: list) -> dict:
    """PUT (replace) the full artifact allowlist for a given artifact type.

    `matchers` is a list of {"artifact": str, "match_type": str}.
    Per the API, this REPLACES the entire allowlist for that artifact type.
    Requires metastore admin or the MANAGE ALLOWLIST privilege.
    """
    artifact_type = artifact_type.strip().upper()
    if artifact_type not in VALID_ARTIFACT_TYPES:
        raise ValueError(
            f"Invalid artifact_type '{artifact_type}'. Expected one of {sorted(VALID_ARTIFACT_TYPES)}"
        )

    clean = []
    for m in matchers:
        artifact = (m.get("artifact") or "").strip()
        match_type = (m.get("match_type") or "PREFIX_MATCH").strip().upper()
        if not artifact:
            continue
        if match_type not in VALID_MATCH_TYPES:
            raise ValueError(
                f"Invalid match_type '{match_type}' for artifact '{artifact}'. "
                f"Expected one of {sorted(VALID_MATCH_TYPES)}"
            )
        clean.append({"artifact": artifact, "match_type": match_type})

    body = {"artifact_matchers": clean}
    resp = w.api_client.do("PUT", f"{_ALLOWLIST_BASE}/{artifact_type}", body=body)
    resp.setdefault("artifact_matchers", [])
    return resp


# COMMAND ----------

# MAGIC %md ## Volume metadata, owners & permissions

# COMMAND ----------

def parse_volume_path(path: str):
    """Return {catalog, schema, volume, full_name, subpath} for a /Volumes/... path.

    Returns None for anything that is not a UC volume path (e.g. maven coords,
    dbfs:/ paths, workspace files).
    """
    if not path:
        return None
    m = _VOLUME_PATH_RE.match(path.strip())
    if not m:
        return None
    catalog, schema, volume, subpath = m.group(1), m.group(2), m.group(3), m.group(4) or ""
    return {
        "catalog": catalog,
        "schema": schema,
        "volume": volume,
        "full_name": f"{catalog}.{schema}.{volume}",
        "subpath": subpath,
    }


def get_volume_info(full_name: str) -> dict:
    """GET Unity Catalog volume metadata (includes `owner`)."""
    return w.api_client.do("GET", f"/api/2.1/unity-catalog/volumes/{full_name}")


def get_volume_grants(full_name: str) -> dict:
    """GET permissions (privilege assignments) on a volume securable."""
    return w.api_client.do(
        "GET", f"/api/2.1/unity-catalog/permissions/volume/{full_name}"
    )


def get_current_metastore() -> dict:
    """Summary of the metastore assigned to the current workspace."""
    try:
        return w.api_client.do("GET", "/api/2.1/unity-catalog/metastore_summary")
    except Exception as e:  # noqa: BLE001 - best effort metadata only
        return {"error": str(e)}


# COMMAND ----------

# MAGIC %md ## Small utilities

# COMMAND ----------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def current_user() -> str:
    try:
        return w.current_user.me().user_name
    except Exception:  # noqa: BLE001
        return "unknown"


def workspace_host() -> str:
    try:
        return w.config.host
    except Exception:  # noqa: BLE001
        return "unknown"


def pretty(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, default=str)


print("[_common] helpers loaded: get_allowlist, set_allowlist, get_volume_info, "
      "get_volume_grants, parse_volume_path, get_current_metastore")
