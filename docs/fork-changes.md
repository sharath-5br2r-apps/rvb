# Comprehensive Downstream Fork Changes

This document details all structural, behavioural, architectural, and tooling differences implemented in **`sharath-5br2r-apps/revanced-morphe-xposed-builder`** relative to upstream **`nullcpy/rvb`**.

---

## 1. Engine & Build Execution (`scripts/build.sh`, `scripts/utils.sh`)

### A. Zero-Patches Rejection Policy
- **Upstream**: Emitted a soft warning (`[!] No applied patches parsed from generic CLI output`) and continued, resulting in publishing unpatched stock binaries into releases and manifests.
- **Fork**: Enforces a strict validation gate. If `applied_patches_count == 0` for Morphe or ReVanced CLI workflows, the engine aborts the app build (`return 1`), preventing corrupted or stock artifacts from reaching release assets and catalog manifests.

### B. Dual Module Packaging for Stable Builds
- **Upstream**: Built only one module zip per target (`-stable` or `-beta`), corresponding to the build's channel.
- **Fork**: When building root modules on the stable channel, the engine builds and signs **both** the primary `-stable` module (`stable/<module>.json`) and a companion `-beta` module (`beta/<module>.json`). Beta channel runs continue to build only `-beta`.

### C. Module Update JSON Layout (`updateJson`)
- **Upstream**: Flattened or customized update file naming schemes.
- **Fork**: Standardized `update_json_path()` to match Magisk/KernelSU updater expectations:
  - Stable pointers: `stable/<module-id>.json`
  - Beta pointers: `beta/<module-id>.json`
  - Fully mirrors the directory structure on the `update` branch.

### D. JSONL Telemetry & Logging
- **Upstream**: Used JSON arrays in `error.json` and `build_log.json`. Under parallel steps or concurrent app builds, merging JSON arrays led to parse errors and clobbered data.
- **Fork**: Standardized all runtime logging on JSON Lines (`error.jsonl` and `build_log.jsonl`). Appending is atomic, lock-free, and resilient. Utilities (`append_build_log.py`, `generate_error_markdown.py`, `aggregate_all_workflow_logs.py`, `build_aggregate_logs.sh`) were refactored to consume line-delimited records.

### E. Prebuilt Tool Verification & Arch Requirements
- Enforces SHA-256 and structural verification of prebuilt binaries (AAPT2, apksigner, CLI JARs) in `get_prebuilts()`.
- Validates that downloaded binaries strictly fulfill requested ABIs (arm64-v8a vs armeabi-v7a vs universal).

---

## 2. Scraping & Cloudflare Bypass (`scripts/cf_get.py`, `scripts/apkmirror_search.py`, `scripts/uptodown.py`)

- **APKMirror Link Resolution**: Fixed regular expressions in `apkmirror_search.py` and `cf_get.py` where intermediate interstitial links or bundle badges caused 404s or misidentified variant download links.
- **CF Bypass Fallbacks**: Added multi-tier fallback support across `CFB_URL` (FlareSolverr/CF-Bypasser) and `TRAWL_URL` endpoints, rejecting challenge pages (HTTP 200 containing Cloudflare turnstile/challenge tokens) and falling back cleanly to secondary methods.
- **Uptodown API Handling**: Enhanced Uptodown download URL resolution and fallback parsing.

---

## 3. CI Pipelines & Matrix Orchestration (`.github/workflows/ci.yml`, `build.yml`, `cleanup.yml`)

### A. Large-Scale Batch Partitioning
- **Upstream**: Relied on monolithic builds or sequential processing.
- **Fork**:
  - Implemented 16-way partitioned batch build matrix (`build_batch` with `configs/batch/config.part*.json`).
  - Added parallel partitioned builders for Dev (`build_dev_1` .. `5`), Stable (`build_stable_1` .. `5`), and Latest (`build_latest_1` .. `5`).
  - Implemented `ci_generate_configs.sh` and `ci_resolve_triggers.sh` to compile merged TOMLs and dynamically split config payloads across partitions.

### B. Consolidated Update Branch Aggregation
- **Upstream**: Parallel runners wrote to the update branch individually, resulting in push races, or committed intermediate directories into Git.
- **Fork**:
  - `build_aggregate_logs.sh` gathers module JSONs from all partition artifacts directly into unified destination folders (`aggregated_out/stable/` and `aggregated_out/beta/`) and changelogs into `aggregated_out/changelogs/`.
  - In `ci.yml`, transient directories (`logs_artifacts/`, `batch_logs/`, etc.) are purged prior to git staging, guaranteeing that only `stable/`, `beta/`, and `changelogs/` are committed to the `update` branch.

### C. Release Channel Mapping & Tagging
- **Dev/Beta**, **Batch Beta (`Batch Build (Both)`)**, and **Absolute Latest (`latest`)**:
  - Target `ARCHIVE_TAG: beta`.
  - Marked with GitHub pre-release flag (`--prerelease`).
- **Stable** and **Batch Stable (`Batch Build (Stable)`)**:
  - Target `ARCHIVE_TAG: stable`.
  - Created as regular stable GitHub releases.

### D. Cleanup Resilience
- `cleanup.yml` and `cleanup-archive-assets.py`:
  - Gracefully handle 404s when archive tags do not yet exist.
  - Support `cleanup_all_releases: true` to delete all releases and orphan tags cleanly without throwing unhandled exceptions.

---

## 4. Documentation & Developer Tooling (`docs/`, `scripts/`)

- **Local Execution Support (`docs/local-build.md`)**:
  - Complete instructions for local Termux and Linux builds with `scripts/build.sh`.
  - Helper scripts: `scripts/fetch_local_data.sh` and `scripts/fetch_versions.sh`.
- **Manual Config Generation**:
  - `scripts/generate_manual_config.sh` compiles merged TOML configs using `ci_merge_patch_tomls.py`.
- **Orphaned Script Cleanup**:
  - Pruned unused legacy scripts: `merge_archive_manifest.sh`, `ci_compile_base_configs.sh`, `ci_aggregate_build_json.py`, and `scripts/generate_ci_configs.sh`.
