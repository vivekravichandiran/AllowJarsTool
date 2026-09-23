# Databricks notebook source
# MAGIC %md
# MAGIC # Part A — Export metastore Allow-Jars (Artifact Allowlist)
# MAGIC
# MAGIC Exports **everything** about the metastore artifact allowlist and saves it as
# MAGIC a JSON file in a Unity Catalog volume.
# MAGIC
# MAGIC For each configured artifact type (`LIBRARY_JAR`, `INIT_SCRIPT`, `LIBRARY_MAVEN`)
# MAGIC this notebook captures:
# MAGIC
# MAGIC 1. The **allowlist matchers** (artifact path / maven coordinate + match type),
# MAGIC    plus `metastore_id`, `created_by`, `created_at` — straight from
# MAGIC    [`GET /api/2.1/unity-catalog/artifact-allowlists/{artifact_type}`](https://docs.databricks.com/api/uc-artifact-allowlists/v1/artifact-allowlist).
# MAGIC 2. For every allowlisted `/Volumes/...` path — the referenced **volume**
# MAGIC    metadata (type, storage location, comment, created/updated), its
# MAGIC    **owner**, and its full **permissions** (privilege assignments).
# MAGIC
# MAGIC The result is written to `<OUTPUT_VOLUME_PATH>/allowlist_export_<timestamp>.json`.
# MAGIC
# MAGIC > **Requires:** metastore admin, or the `MANAGE ALLOWLIST` privilege on the metastore.

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

# MAGIC %md ## Parameters

# COMMAND ----------

dbutils.widgets.text(
    "artifact_types",
    "LIBRARY_JAR,INIT_SCRIPT,LIBRARY_MAVEN",
    "Artifact types (comma separated)",
)
dbutils.widgets.text(
    "output_volume_path",
    "/Volumes/main/default/allowlist_backups",
    "Output volume path (folder)",
)
dbutils.widgets.dropdown(
    "enrich_volumes", "true", ["true", "false"], "Enrich referenced volumes (owner/permissions)?"
)

ARTIFACT_TYPES = [t.strip().upper() for t in dbutils.widgets.get("artifact_types").split(",") if t.strip()]
OUTPUT_VOLUME_PATH = dbutils.widgets.get("output_volume_path").rstrip("/")
ENRICH_VOLUMES = dbutils.widgets.get("enrich_volumes").lower() == "true"

print(f"Artifact types    : {ARTIFACT_TYPES}")
print(f"Output volume path: {OUTPUT_VOLUME_PATH}")
print(f"Enrich volumes    : {ENRICH_VOLUMES}")

# COMMAND ----------

# MAGIC %md ## 1. Read the allowlist for each artifact type

# COMMAND ----------

allowlists = {}
for atype in ARTIFACT_TYPES:
    try:
        info = get_allowlist(atype)
        allowlists[atype] = info
        n = len(info.get("artifact_matchers", []))
        print(f"  {atype:16s}: {n} matcher(s)")
    except Exception as e:  # noqa: BLE001
        print(f"  {atype:16s}: ERROR - {e}")
        allowlists[atype] = {"error": str(e), "artifact_matchers": []}

# COMMAND ----------

# MAGIC %md ## 2. Resolve referenced volumes (owner + permissions)

# COMMAND ----------

# Collect unique volume full-names referenced by any allowlisted artifact path.
volume_refs = {}  # full_name -> {"parsed": ..., "referenced_by": set()}
for atype, info in allowlists.items():
    for matcher in info.get("artifact_matchers", []):
        parsed = parse_volume_path(matcher.get("artifact", ""))
        if not parsed:
            continue
        fn = parsed["full_name"]
        entry = volume_refs.setdefault(fn, {"parsed": parsed, "referenced_by": set()})
        entry["referenced_by"].add(f"{atype}:{matcher.get('artifact')}")

volumes = []
if ENRICH_VOLUMES and volume_refs:
    for full_name, ref in sorted(volume_refs.items()):
        record = {
            "full_name": full_name,
            "catalog_name": ref["parsed"]["catalog"],
            "schema_name": ref["parsed"]["schema"],
            "name": ref["parsed"]["volume"],
            "referenced_by": sorted(ref["referenced_by"]),
        }
        try:
            vi = get_volume_info(full_name)
            record["info"] = vi
            record["owner"] = vi.get("owner")
            record["volume_type"] = vi.get("volume_type")
            record["storage_location"] = vi.get("storage_location")
            record["comment"] = vi.get("comment")
        except Exception as e:  # noqa: BLE001
            record["info_error"] = str(e)
        try:
            record["permissions"] = get_volume_grants(full_name).get("privilege_assignments", [])
        except Exception as e:  # noqa: BLE001
            record["permissions_error"] = str(e)
        volumes.append(record)
        print(f"  {full_name}: owner={record.get('owner')} "
              f"perms={len(record.get('permissions', []))}")
elif not volume_refs:
    print("  (no /Volumes/... paths referenced in the allowlist)")
else:
    print("  (volume enrichment disabled)")

# COMMAND ----------

# MAGIC %md ## 3. Assemble the export document

# COMMAND ----------

export_doc = {
    "export_metadata": {
        "exported_at": now_iso(),
        "exported_by": current_user(),
        "workspace_host": workspace_host(),
        "metastore": get_current_metastore(),
        "artifact_types": ARTIFACT_TYPES,
        "schema_version": "1.0",
    },
    "allowlists": allowlists,
    "volumes": volumes,
}

print(pretty(export_doc)[:4000])

# COMMAND ----------

# MAGIC %md ## 4. Save the JSON to the output volume

# COMMAND ----------

# Make sure the destination folder exists (works for UC volume paths).
try:
    dbutils.fs.mkdirs(OUTPUT_VOLUME_PATH)
except Exception as e:  # noqa: BLE001
    print(f"WARN: could not mkdirs {OUTPUT_VOLUME_PATH}: {e}")

timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
out_file = f"{OUTPUT_VOLUME_PATH}/allowlist_export_{timestamp}.json"

# /Volumes paths are FUSE-mounted, so a plain file write works.
with open(out_file, "w") as f:
    json.dump(export_doc, f, indent=2, sort_keys=True, default=str)

# Also refresh a stable "latest" pointer for easy import.
latest_file = f"{OUTPUT_VOLUME_PATH}/allowlist_export_latest.json"
with open(latest_file, "w") as f:
    json.dump(export_doc, f, indent=2, sort_keys=True, default=str)

total_matchers = sum(len(v.get("artifact_matchers", [])) for v in allowlists.values())
print(f"Exported {total_matchers} matcher(s) across {len(ARTIFACT_TYPES)} artifact type(s).")
print(f"Enriched {len(volumes)} referenced volume(s).")
print(f"Wrote: {out_file}")
print(f"Wrote: {latest_file}  (stable 'latest' pointer)")

# Return the path so this notebook can be chained via dbutils.notebook.run(...).
dbutils.notebook.exit(out_file)
