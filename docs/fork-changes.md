# Downstream Fork Changes

This document provides a comprehensive log of architectural and behavioural changes implemented in this fork (`sharath-5br2r-apps/revanced-morphe-xposed-builder`) relative to upstream (`nullcpy/rvb`).

---

## 1. Engine & Patching (`scripts/build.sh`, `scripts/utils.sh`)

- **Empty Patch Rejection**:
  - ReVanced and Morphe patch workflows now reject builds when 0 patches are applied (`applied_patches_count == 0`), throwing a fatal error instead of issuing a soft warning that would publish an unpatched application.
- **Strict Arch Validation & Prebuilt Verification**:
  - Validates prebuilt CLI/bundle JAR integrity in `get_prebuilts()`.
  - Enforces requested architecture constraints across APKMirror, Uptodown, and GitHub download chains.
- **Dual Module Generation for Stable Builds**:
  - When building root modules on stable channels, the engine automatically creates both the stable module (`stable/<module>.json`) and a companion beta channel module (`beta/<module>.json`).
  - Beta channel builds produce only the beta module.
- **Module Update Pointer Layout**:
  - In `update_json_path()`, paths are mapped to match standard channel root folders (`stable/<module>.json` and `beta/<module>.json`), ensuring compatibility with Magisk and KernelSU updater clients.
- **JSONL Logging Pipeline**:
  - Standardized error and build telemetry to JSON Lines format (`error.jsonl` and `build_log.jsonl`) for robust concurrent appending and atomic record extraction.

---

## 2. Scraping & Downloading (`scripts/cf_get.py`, `scripts/apkmirror_search.py`)

- **APKMirror Scraper Resiliency**:
  - Fixed version link matching to avoid false positives and dead-end URLs.
  - Added robust detection and fallback handling for Cloudflare bypass services (`CFB_URL` and `TRAWL_URL`).
  - Enhanced error handling for APKMirror rate limiting and bundle URL extraction.

---

## 3. Workflows & CI Pipelines (`.github/workflows/ci.yml`, `build.yml`, `cleanup.yml`)

- **Batch Partitioning & Dynamic Matrix**:
  - Support for partitioned batch building across multiple jobs (`configs/batch/config.part*.json`, `configs/stable/config.part*.json`, `configs/beta/config.part*.json`, and `configs/both/config.part*.json`).
  - Config partition consolidation in `ci_generate_configs.sh` and `ci_resolve_triggers.sh`.
- **Release Channel & Tag Alignment**:
  - **Batch Beta (`Batch Build (Both)`)**, **Dev (`beta`)**, and **Absolute Latest (`latest`)** map to `ARCHIVE_TAG: beta` and are marked with `--prerelease`.
  - **Batch Stable (`Batch Build (Stable)`)** and **Stable** map to `ARCHIVE_TAG: stable` and publish as full stable releases.
- **Consolidated Update Branch Aggregation**:
  - `build_aggregate_logs.sh` consolidates module pointers from all parallel build parts directly into `aggregated_out/stable/` and `aggregated_out/beta/`, and release changelogs into `aggregated_out/changelogs/`.
  - Temporary folders (`logs_artifacts/`, `batch_logs/`, etc.) are purged prior to staging on the `update` branch, preventing working tree pollution.
- **Archive Cleanup Resilience (`cleanup.yml`, `cleanup-archive-assets.py`)**:
  - Gracefully handles missing archive releases (404s).
  - Deletes all releases and archive assets cleanly when `cleanup_all_releases: true` or when the release asset query returns null.

---

## 4. Documentation & Local Build Tooling (`docs/`, `scripts/`)

- **Local Execution Guide (`docs/local-build.md`)**:
  - Complete documentation for running `scripts/build.sh` on Linux and Android (Termux).
  - Helper scripts: `scripts/fetch_local_data.sh` and `scripts/fetch_versions.sh`.
- **Pruned Unused Upstream Helpers**:
  - Removed obsolete notification queue scripts and abandoned single-pass scripts (`merge_archive_manifest.sh`, `ci_compile_base_configs.sh`, `ci_aggregate_build_json.py`, `generate_ci_configs.sh`).
