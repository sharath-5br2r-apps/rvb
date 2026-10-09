# 2 — Website Files and Manifests Live in Branch (Downstream Fork)

**Status:** accepted (2026-10-09)  
**Affects:** `.github/scripts/merge_archive_branch.sh`, `.github/scripts/cleanup_website_branch.sh`, `.github/scripts/rebuild_catalog.py`, `.github/workflows/build.yml`, `.github/workflows/cleanup.yml`, `.github/workflows/update-website.yml`, `.github/workflows/rebuild-catalog.yml`, `_config.yml`

## Context

Upstream `nullcpy/rvb` maintains an independent `website` branch that hosts JSON manifests, and delegates website rendering and catalog compilation to an external repository (`nullcpy.github.io`) triggered through webhook repository dispatches with personal access tokens (`WEBSITE_DISPATCH_TOKEN`). Furthermore, upstream's catalog rebuild script (`rebuild_catalog.py`) dynamically cloned external repositories (`RVB_REPO`, `RVB_NAMING_DIR`) to inspect manifests and borrow architecture parsing rules from `.github/scripts/naming.py`.

In this downstream fork (`sharath-5br2r-apps/revanced-morphe-xposed-builder`), the catalog website is self-contained within this repository and deployed via GitHub Pages from the `gh-pages` branch. The legacy `website` branch was redundant and fragmented CI operations.

## Decision

1. **Retire `website` Branch in Favor of `gh-pages`**:
   - The obsolete `website` branch is retired. All release manifests and catalog web assets live on the `gh-pages` branch.
   - Per-release manifests are committed to `gh-pages:manifests/<tag>.json`.
   - Cumulative archive manifests are merged and committed to `gh-pages:manifests/archive/{stable,beta}.json`.
   - Manifest lifecycle scripts (`merge_archive_branch.sh` and `cleanup_website_branch.sh`) checkout, write, and clean paths on `gh-pages` directly.

2. **Self-Contained Catalog Rebuilding (Eliminating `git clone`)**:
   - `rebuild_catalog.py` reads manifests directly from local relative directories (`manifests/` and `manifests/archive/`) without cloning external git repositories during CI.
   - Naming rules (`.github/scripts/naming.py`) are maintained locally within the repository on both `main` and `gh-pages`, allowing stdlib-only architecture and filename parsing.
   - Canonical repository and site defaults:
     - Site URL: `https://sharath-5br2r.github.io/apps`
     - Default RVB repo: `sharath-5br2r/apps` (with continued support for companion workflows `Eden-Workflow`, `Dolphin-Extra`, `LeviLaunchroid-Extra`, and `ZalithLauncher2-Extra`).

3. **In-Repo Workflow Dispatching**:
   - External HTTP `curl` dispatches using repository tokens are replaced with native GitHub Actions workflow triggers.
   - `.github/workflows/rebuild-catalog.yml` is defined on `main` with `workflow_dispatch` and `workflow_call` triggers, checking out `gh-pages` to execute `rebuild_catalog.py` and commit generated `data.json` and `data.json.gz`.
   - `build.yml` and `cleanup.yml` invoke catalog rebuilds directly using `gh workflow run rebuild-catalog.yml` (or via workflow calls in `update-website.yml`), eliminating external network dependencies and token requirements.

## Verification

- Shell scripts (`merge_archive_branch.sh`, `cleanup_website_branch.sh`) validate with `bash -n`.
- Python scripts (`rebuild_catalog.py`, `generate_release_notes.py`) validate with `python3 -m py_compile`.
- Catalog build runs against `manifests/` and `manifests/archive/` on `gh-pages` and outputs valid `data.json` and `data.json.gz`.
