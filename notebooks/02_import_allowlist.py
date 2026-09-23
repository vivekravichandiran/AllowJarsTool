# Databricks notebook source
# MAGIC %md
# MAGIC # Part B — Import metastore Allow-Jars (Artifact Allowlist)
# MAGIC
# MAGIC Reads a JSON export produced by **Part A** and applies the allowlist back to
# MAGIC the metastore using
# MAGIC [`PUT /api/2.1/unity-catalog/artifact-allowlists/{artifact_type}`](https://docs.databricks.com/api/uc-artifact-allowlists/v1/artifact-allowlist).
# MAGIC
# MAGIC The Set API **replaces the entire allowlist** for an artifact type, so this
# MAGIC notebook offers two modes:
# MAGIC
# MAGIC | Mode | Behaviour |
# MAGIC |---|---|
# MAGIC | `replace` | PUT exactly the matchers from the JSON (authoritative restore). |
# MAGIC | `merge` *(patch-like)* | Read the current allowlist, union it with the JSON matchers, then PUT — nothing existing is removed. |
# MAGIC
# MAGIC A `dry_run` toggle lets you preview the exact payload before anything is written.
# MAGIC
# MAGIC > **Requires:** metastore admin, or the `MANAGE ALLOWLIST` privilege on the metastore.

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

# MAGIC %md ## Parameters

# COMMAND ----------

dbutils.widgets.text(
    "input_json_path",
    "/Volumes/main/default/allowlist_backups/allowlist_export_latest.json",
    "Input JSON path",
)
dbutils.widgets.text(
    "artifact_types",
    "LIBRARY_JAR,INIT_SCRIPT,LIBRARY_MAVEN",
    "Artifact types to import (comma separated)",
)
dbutils.widgets.dropdown("import_mode", "merge", ["merge", "replace"], "Import mode")
dbutils.widgets.dropdown("dry_run", "true", ["true", "false"], "Dry run (preview only)?")

INPUT_JSON_PATH = dbutils.widgets.get("input_json_path")
IMPORT_TYPES = [t.strip().upper() for t in dbutils.widgets.get("artifact_types").split(",") if t.strip()]
IMPORT_MODE = dbutils.widgets.get("import_mode").lower()
DRY_RUN = dbutils.widgets.get("dry_run").lower() == "true"

print(f"Input JSON     : {INPUT_JSON_PATH}")
print(f"Artifact types : {IMPORT_TYPES}")
print(f"Import mode    : {IMPORT_MODE}")
print(f"Dry run        : {DRY_RUN}")

# COMMAND ----------

# MAGIC %md ## 1. Load the export document

# COMMAND ----------

with open(INPUT_JSON_PATH, "r") as f:
    doc = json.load(f)

meta = doc.get("export_metadata", {})
print("Loaded export produced:")
print(f"  at     : {meta.get('exported_at')}")
print(f"  by     : {meta.get('exported_by')}")
print(f"  host   : {meta.get('workspace_host')}")
print(f"  types  : {list(doc.get('allowlists', {}).keys())}")

source_allowlists = doc.get("allowlists", {})

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Build the target matcher set per artifact type
# MAGIC
# MAGIC In `merge` mode we union the incoming matchers with what is already live so
# MAGIC nothing gets dropped. In `replace` mode we take the JSON as the source of truth.

# COMMAND ----------

def _matcher_key(m):
    return ((m.get("artifact") or "").strip(), (m.get("match_type") or "PREFIX_MATCH").strip().upper())


plans = {}  # artifact_type -> {"current": [...], "incoming": [...], "final": [...]}

for atype in IMPORT_TYPES:
    src = source_allowlists.get(atype, {})
    if "error" in src:
        print(f"  {atype}: skipped (export recorded an error: {src['error']})")
        continue
    incoming = [
        {"artifact": m.get("artifact"), "match_type": (m.get("match_type") or "PREFIX_MATCH")}
        for m in src.get("artifact_matchers", [])
        if (m.get("artifact") or "").strip()
    ]

    current = []
    if IMPORT_MODE == "merge":
        try:
            current = get_allowlist(atype).get("artifact_matchers", [])
        except Exception as e:  # noqa: BLE001
            print(f"  {atype}: could not read current allowlist for merge ({e}); treating as empty")

    # De-dupe by (artifact, match_type), preserving order: current first, then new.
    seen, final = set(), []
    for m in (current + incoming) if IMPORT_MODE == "merge" else incoming:
        k = _matcher_key(m)
        if k in seen:
            continue
        seen.add(k)
        final.append({"artifact": k[0], "match_type": k[1]})

    plans[atype] = {"current": current, "incoming": incoming, "final": final}
    print(f"  {atype}: current={len(current)} incoming={len(incoming)} -> final={len(final)}")

# COMMAND ----------

# MAGIC %md ## 3. Preview the exact PUT payloads

# COMMAND ----------

for atype, plan in plans.items():
    print(f"\n=== {atype} (PUT body) ===")
    print(pretty({"artifact_matchers": plan["final"]}))

# COMMAND ----------

# MAGIC %md ## 4. Apply (skipped when Dry run = true)

# COMMAND ----------

if DRY_RUN:
    print("DRY RUN: nothing was written. Set the `dry_run` widget to 'false' to apply.")
else:
    results = {}
    for atype, plan in plans.items():
        try:
            resp = set_allowlist(atype, plan["final"])
            results[atype] = {
                "status": "OK",
                "matchers_written": len(resp.get("artifact_matchers", [])),
            }
            print(f"  {atype}: OK ({results[atype]['matchers_written']} matchers now live)")
        except Exception as e:  # noqa: BLE001
            results[atype] = {"status": "ERROR", "error": str(e)}
            print(f"  {atype}: ERROR - {e}")
    print("\nSummary:")
    print(pretty(results))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Note on volume owners & permissions
# MAGIC
# MAGIC The export also captures each referenced volume's **owner** and **permissions**
# MAGIC for auditing / disaster-recovery context. The Artifact Allowlist API only
# MAGIC governs the allowlist itself, so those grants are *not* re-applied here by
# MAGIC design (restoring UC grants is a separate, higher-risk operation). The data
# MAGIC is available in `doc["volumes"]` if you choose to reconcile them manually.
