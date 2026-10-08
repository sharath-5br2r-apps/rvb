# Comprehensive Downstream Fork Changes

This document provides an exhaustive, technical account of all architectural, behavioural, and operational differences implemented in **`sharath-5br2r-apps/revanced-morphe-xposed-builder`** relative to upstream **`nullcpy/rvb`**, derived directly from codebase inspection and `git diff upstream/main...HEAD`.

---

## 1. Local Build CLI & Execution (`scripts/build.sh`)

### A. Comprehensive Command-Line Argument Parser
- **Upstream**: Accepted only positional configuration files (`$1`) and preset environment variables; lacked dedicated flag parsing or help menus.
- **Fork**: Added full GNU-style option parsing supporting `--option=val` and `--option val`:
  - `--config=PATH`: Explicit configuration file path (defaults to `config.toml` or first positional argument).
  - `--allowed-apps=REGEX`: Filter applications to build by table name matching a regular expression.
  - `--output=DIR`: Overrides default build artifact destination directory (`build/`).
  - `--patches-version=VER`: Overrides the patch release channel (`stable`, `beta`, `both`, or specific version tag).
  - `--clean`: Purges all temporary work directories (`temp/`, `build/`, `build.md`) and exits immediately.
  - `--help` / `-h`: Displays formatted CLI reference manual with environment variable documentation.

### B. Ad-Hoc Command-Line Table Filtering
- **Upstream**: Required editing TOML/JSON configs or setting workflow inputs.
- **Fork**: Added positional app filter arguments:
  ```bash
  ./scripts/build.sh configs/patches/morphe.toml YouTube Twitter   # include only
  ./scripts/build.sh configs/patches/morphe.toml !YouTube          # exclude
  ```

### C. Concurrency Isolation & Post-Build Summaries
- **Scratch Directory Isolation**: Deterministically purges worker scratch files (`temp/tmp.*`, `*-merge-tmp*`, `morphe-stage-*`) per process.
- **Partition Support**: Propagates `CURRENT_BUILD_PART` to isolate logs and lock contexts when running parallel CI segments.
- **Automated Step Summary**: Automatically invokes `generate_error_markdown.py` post-build to emit `error.md` for GitHub Actions step summaries and local terminal review.

---

## 2. Core Build Utilities & Engine (`scripts/utils.sh`)

### A. Zero-Patch Rejection Policy
- **Upstream**: When patchers produced 0 applied patches, upstream printed a warning (`wpr "No applied patches parsed..."`) and continued, resulting in publishing unpatched stock binaries into releases and manifests.
- **Fork**: Enforces a strict validation gate:
  ```bash
  if [ "$applied_json" = "[]" ] && [ -n "$PATCH_OUTPUT" ] && [ "${PATCHER_FLOW:-}" = cli-patch ]; then
      epr "Rejecting build: No applied patches parsed from ${PATCHER_KIND:-cli-patch} CLI output for '$key'."
      rm -f "$target_file" "$apk_output" "$patched_apk" 2>/dev/null || :
      return 1
  fi
  ```

### B. Dual Module Packaging for Stable Builds
- **Upstream**: Packaged only one module zip matching the active build channel.
- **Fork**: When building root modules on the stable channel, the engine generates **both**:
  1. Primary stable module (`<app>-module-v<ver>-<arch>.zip`) with `stable/<id>.json` update URL.
  2. Companion beta module (`<app>-module-v<ver>-<arch>-beta.zip`) with `beta/<id>.json` update URL.
  Beta builds continue to produce only beta modules.

### C. Module Update JSON Layout (`updateJson`)
- **Upstream**: Flattened or customized pointer naming schemes.
- **Fork**: Standardized `update_json_path()` to match Magisk/KernelSU updater expectations:
  - Stable pointers: `stable/<module-id>.json`
  - Beta pointers: `beta/<module-id>.json`
  - Eliminates author/channel duplicate suffixes (`<base_id>-stable` / `<base_id>-beta`).

### D. JSONL Telemetry & Logging
- **Upstream**: Accumulated logs as in-memory JSON arrays in `error.json` and `build_log.json`, which corrupted under concurrent step execution.
- **Fork**: Standardized all telemetry on JSON Lines (`error.jsonl` and `build_log.jsonl`):
  - Added `log_build_event()` for atomic appending.
  - Formatted logger helpers `pr()`, `epr()`, and `wpr()` automatically prefix active `CURRENT_APP_NAME` and `CURRENT_BUILD_PART`.

### E. Expanded Download Providers (`DL_SRCS`) & Options
- **Upstream `DL_SRCS`**: `("cache_repo" "direct" "github" "archive" "apkmirror" "uptodown" "apkpure" "apkcombo")`
- **Fork `DL_SRCS`**: `("local" "direct" "cache_repo" "github" "gitlab" "forgejo" "archive" "apkmirror" "uptodown" "apkpure" "apkcombo")`
- **New Download Sources**:
  - `local-dlurl`: Direct file system loading (`get_local_resp`, `get_local_vers`, `get_local_pkg_name`, `dl_local`). Supports raw paths and `file://` URLs.
  - `gitlab-dlurl`: Native GitLab releases integration (`dl_gitlab`, `get_gitlab_resp`, `get_gitlab_vers`).
  - `forgejo-dlurl`: Native Forgejo/Gitea API releases integration (`dl_forgejo`, `get_forgejo_resp`, `get_forgejo_vers`).
  - Unified Git release downloader (`dl_git_repo`): Dynamically resolves tag versions and matches release assets via `${provider}_dlurl_regex` or `github_asset_regex`.

### F. Patcher Registry Extensions (`patchers.sh`, `patchers.py`)
- **New Patcher Kinds**:
  - `apksigner`: Pure signing workflow (`flow=signing`), skipping patch application.
  - `none`: Passthrough workflow (`flow=passthrough`), taking stock binaries directly.
  - Disaggregated `npatch` and `lspatch` kinds from monolithic `xposed`.
- **Argument Deduplication**: Added `dedup_patcher_args()` to strip redundant flags (like duplicated `-f`, `--force`, or `--continue-on-error`) from CLI invocations.

### G. Keystore & Prebuilt Tooling
- **Keystore Management**:
  - Loads local `.env` configurations automatically when present.
  - Implemented `require_p12()` using Bouncy Castle (`get_bcprov`) to convert BKS keystores to PKCS12 dynamically.
  - Added dedicated `sign_apk` wrapper with apksigner validation.
- **Prebuilt Integrity**:
  - Validates prebuilt CLI and tool JARs via `is_valid_zip_or_jar()` and SHA-256 verification.
  - Enforces native architecture checks via `has_native_arch`.

### H. Extended Build Metadata Extraction
- Expanded `write_build_info()` to capture:
  - `min_sdk` and `version_code` extracted directly from APK manifests.
  - `cli` reference version and name.
  - `failed_patches`, `skipped_patches`, `densities`, and `native_libs` JSON arrays.
  - Granular branding fields: `engine_brand` and `patch_brand`.

---

## 3. Scraping & Download Helpers

### A. APKMirror Scraper (`scripts/apkmirror_search.py`)
- **Prefix Sanitization**: Strips Cloudflare WARP product prefixes (`1.1.1.1 + `) so version numbers parse cleanly.
- **Flexible DPI Input**: Accepts string, list, or JSON dictionary formats for `dpi` configurations.
- **Release Filtering (`rel_filter`)**: Added support for positive and negative variant regex filters (e.g. `!bundle` or `wear-os`).
- **Fat-Bundle Arch Matching**: Expanded fallback hierarchy for multi-ABI and universal packages (`all`, `arm64-v8a + x86_64`, `arm64-v8a + armeabi-v7a`).

### B. Cloudflare Bypass & Fallback Scraper (`scripts/cf_get.py`)
- **Multi-Method Fallback Chain**:
  - Tries direct curl, FlareSolverr (`fs_get`), Cloudflare Bypasser (`cfb_get`), Trawl (`trawl_get`), and `curl_cffi` (`curl_cffi_get`).
  - Intercepts and rejects challenge HTML responses (Cloudflare Turnstile / 200 challenge pages) via `is_challenge()` and `is_valid_download()`.
- **Concurrency Locking**: Added cross-process cookie file synchronization via file locks (`acquire_lock`).
- **Pruned Unused Code**: Removed orphaned `is_cf_html()` function.

---

## 4. Workflows & CI Pipelines (`.github/workflows/ci.yml`, `build.yml`, `cleanup.yml`)

### A. 16-Way Partitioned Batch Builds
- Added `build_batch` matrix job handling 16 config partitions (`configs/batch/config.part*.json`).
- Added parallel partitioned builders for Dev (`build_dev_1`..`5`), Stable (`build_stable_1`..`5`), and Latest (`build_latest_1`..`5`).

### B. Atomic Update Branch Aggregation
- `build_aggregate_logs.sh` gathers module pointers directly into `aggregated_out/stable/` and `aggregated_out/beta/`, and changelogs into `aggregated_out/changelogs/`.
- Transient working directories (`logs_artifacts/`, `batch_logs/`, etc.) are purged prior to git staging, ensuring no build scratch files enter the `update` branch.

### C. Release Tagging & Channel Mapping
- **Beta / Dev / Latest**:
  - Mapped to `ARCHIVE_TAG: beta`.
  - Created as GitHub pre-releases (`--prerelease`).
- **Stable / Batch Stable**:
  - Mapped to `ARCHIVE_TAG: stable`.
  - Created as standard stable GitHub releases.

### D. Cleanup Resilience
- Gracefully handles absent/uninitialized archive releases.
- Supports `cleanup_all_releases: true` to purge all release tags and assets cleanly.

---

## 5. Local Tooling & Maintenance (`scripts/`, `docs/`)

- **`scripts/fetch_local_data.sh`**: Checks out `configs/` and `state/` from the local `data` branch for local development.
- **`scripts/fetch_versions.sh`**: Checks out `state/app_versions.json` and updates target versions locally.
- **`scripts/generate_manual_config.sh`**: Compiles merged TOML configs using `ci_merge_patch_tomls.py`.
- **`scripts/delete_all_releases.sh`**: Interactive CLI utility to delete repository releases.
- **`docs/local-build.md`**: Dedicated reference guide for local Termux and Linux builds.
- **Pruned Orphaned Scripts**: Deleted deprecated `merge_archive_manifest.sh`, `ci_compile_base_configs.sh`, `ci_aggregate_build_json.py`, and `generate_ci_configs.sh`.
