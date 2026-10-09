# Website contract

In this downstream fork, the catalog website and release manifests are unified within this repository:
the builder publishes manifests to `gh-pages`, and GitHub Pages serves the web frontend from `gh-pages`
(`https://sharath-5br2r.github.io/apps`).
Detailed architectural decisions are recorded in
[`docs/decisions/fork/2-Website-Files-Live-In-Branch.md`](decisions/fork/2-Website-Files-Live-In-Branch.md).

## What crosses the boundary

| Channel | Direction | Format | Stability |
|---|---|---|---|
| `gh-pages` manifests | builder → `gh-pages` | `manifests/<tag>.json`, `manifests/archive/{stable,beta}.json`, schema v1 | **the contract**; written by `merge_archive_branch.sh` |
| GitHub Releases API | site → GitHub | asset existence, size, `downloadCount`, browser download URLs | queried live, never cached in git |
| `rebuild-catalog.yml` trigger | builder → workflow | workflow call / `gh workflow run` | native Actions workflow trigger on `gh-pages` |
| `update` branch pointers | phone → rvb | `module.prop` `updateJson` URL + JSON | baked into installed modules |
| Numbered/archive release URLs | site → rvb | `releases/download/<tag>/<file>` | filename grammar is the contract |
| `.github/scripts/naming.py` | shared | Python module | maintained locally in the repo |

## The pipeline across the seam

```
rvb: merge_build_info → build.json → build_make_manifest.py → temp/manifest/build.json
                                                            ↓ (after archive upload)
rvb: gh-pages branch  manifests/<tag>.json  +  manifests/archive/<channel>.json
                                                            ↓ workflow_call / gh workflow run
gh-pages: rebuild-catalog.yml → rebuild_catalog.py → data.json (schema v2) & data.json.gz
```

The catalog is **derived from scratch** every run — fold numbered manifests, fold
archive manifests against live assets, then query the releases API for mutables. A
release or asset that no longer exists simply does not appear; nothing edits
`data.json` in place. That is why a corrupted branch entry is repairable by the
next build rather than permanent.

## From schema v1 to schema v2

Schema v1 (rvb writes; keys listed in
[storage-and-branches.md](storage-and-branches.md)) is per-file and flat. Schema
v2 (the site publishes) is a normalised document: `apps[] → brands[] → variants[]
→ builds[] → assets[]`, with the three repeated lists — applied patches,
changelog URLs, patch-source slugs — collapsed into top-level tables
(`patchSets`, `changelogSets`, `patchSourceSets`) that builds reference by integer
index (`patchSetRef`, `changelogRef`, `patchSourceRef`). Dedup is keyed on the
ordered list, so only byte-identical repeats collapse; an empty list is omitted
entirely.

**Per-file values are authoritative, not per-app.** A numbered build publishes each
arch independently, so one build can carry `arm64` at the newest app version and
`arm` at an older fallback, and their applied-patch sets can differ. rvb therefore
stamps `version` and `appliedPatches` from each file's own name/arch (never a
collapsed per-app scalar). The numbered build **card** is keyed by the build tag, so
those mixed versions stay under one "Build <tag>" entry that lists every version it
published (`build.versions`) and shows the version on each asset row; only the
archive release keys its cards by version (it is a version history). When a build's
arches carry distinct patch sets, the applied-patches view exposes per-arch tabs
(like the Stable/Beta channel tabs) so each arch's list is shown.

| v1 (rvb) | v2 (site) | Notes |
|---|---|---|
| key = asset filename | `assets[].name` | the join key for everything mutable |
| `name`, `version`, `arch`, `fileType` | asset + build fields | arch ordering: `arm64`, `arm`, `all`, `universal`, `x86_64`, `x86`. A build publishes only the arches it actually produced, so an app may carry a subset (a single-ABI app has one arch entry) — the catalog derives from the manifests present, never assumes both channels exist ([decisions/0007](decisions/0007-requested-arch-is-a-hard-requirement.md)) |
| `appKey`, `appName` | `apps[]` identity | app grouping |
| `brandKey`, `brandName`, `variant`, `subVariant` | `brands[]`, `variants[]` | variant is `null` for `default` |
| `appliedPatches[]`, `changelogs[]`, `patchSources[]` | the ref tables above | |
| `originBuild` | build identity for archived files | an archive entry still names the numbered build it came from |
| `meta.channel`, `meta.kind` | `releaseType`, `isArchive` | `kind: "archive"` ⇒ `isArchive: true` |
| — (never in the manifest) | `size`, `downloadCount`, download URL | live from the Releases API |

Mutable numbers are never stored in git on either side: existence, size and
download counts belong to the releases, immutable build-time facts belong to the
manifests. Splitting them that way is what makes a stale catalogue impossible
rather than merely unlikely.

## Filename parsing is shared, not duplicated

`arch` extraction/normalisation, `file_prefix` and key normalisation have exactly one
implementation: [.github/scripts/naming.py](../.github/scripts/naming.py). The site's
`rebuild_catalog.py` **imports** it — `rebuild-catalog.yml` performs a blob-filtered,
sparse clone of `main` and points `RVB_NAMING_DIR` at `.github/scripts`, and a local
run resolves the same file from a `rvb` checkout beside the site repo. If the module
cannot be found the rebuild exits with `FATAL:` rather than falling back to anything.

That closes what used to be the weakest seam in the design: the site carried a
hand-copied mirror held together by "change both in the same series of commits",
and divergence would have been silent — an app grouping under the wrong architecture
or splitting into two variant cards. History and rejected alternatives:
[decisions/0006](decisions/0006-filename-parsing-is-imported-not-mirrored.md).

Practical consequence for editing: a behaviour change in `naming.py` reaches the site
on the next catalogue rebuild with no second edit, so run `rebuild-catalog.yml` with
`dry_run: true` and read the diff before merging one. Keep `naming.py` stdlib-only —
a third-party import there would break the site's dependency-free rebuild job.

## Degraded entries are visible by design

If a live asset has no manifest entry, the rebuild synthesises a minimal one from
its filename so **download buttons never disappear**. Such entries have no applied
patch list, and the site renders them as degraded nameless "patched" wrapper
cards. That is intentional: a missing record degrades visibly instead of hiding
files from users. The same rule governs rvb's repair tooling — check the
fallback count in a dry run before applying it.

## Circuit breakers

Both sides can lose an input, so both refuse to publish a collapse:

| Guard | Where | Fires when |
|---|---|---|
| `MIN_RATIO` (default `0.6`) | site `rebuild_catalog.py` | the new catalogue retains fewer than 60% of the previous apps/builds → abort (`FORCE=1` overrides) |
| fetch failure = job failure | rvb `merge_archive_branch.sh`, `fetch_data_branch.sh` | the previous branch state could not be read — no "start from empty" path exists |
| merge sanity gate | rvb `merge_archive_branch.sh` | the merged archive manifest kept fewer entries than `|union(old,new) ∩ live|` |
| push retry with rebase | both manifest/branch writers | a concurrent branch update; a genuine conflict defers to the next run rather than forcing |

The 2026-09-24 archive collapse is the reason the first two exist: a transient
download failure fell back to an empty base and the cumulative manifest restarted
from one build. Storage moved to a branch so that failure mode cannot be
expressed — the full account is
[decisions/0002](decisions/0002-manifests-live-on-a-branch.md).

## Changing a format without breaking the site

1. **Additive first.** A new manifest key is invisible to the site; a new *build*
   object shape is not, so the site's `rebuild_catalog.py` and its `CONFIG.md`
   schema section change in the same series. Filename-parsing rules do not have this
   problem — they live in one module both sides use.
2. **Never reinterpret an existing key.** Filenames, `updateJson` paths, JSON key
   names and the branch layout are wire formats already in users' hands. Introduce
   a new key and let the old one age out, or accept a forced re-flash.
3. **Bump `schema`** in the manifest envelope for a breaking change, and make the
   consumer reject an unknown major version loudly instead of half-reading it.
4. **Verify both ends before pushing.** Locally:
   `python3 .github/scripts/rebuild_catalog.py --repos sharath-5br2r/apps --manifest-dir . --out /tmp/data.json.new --existing data.json`
   then diff `/tmp/data.json.new` against `data.json` ignoring `updated_at` —
   exactly what the workflow's report step does. On GitHub: run
   `rebuild-catalog.yml` with `dry_run: true`.
5. **Remember the pruning coupling.** Archive assets disappear (2 newest versions
   per app + arch) and their manifest entries drop out at the next merge; module
   `updateJson` pointers resolve against the *archive* release, so a pruned file
   breaks a pending module update rather than only the catalogue.
