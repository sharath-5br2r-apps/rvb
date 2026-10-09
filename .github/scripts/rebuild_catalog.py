#!/usr/bin/env python3
"""Rebuild data.json from release manifests and rvb branch manifests.

The catalog is derived from scratch on every run:
  data.json = fold(numbered release manifests)      -> numbered build entries
            + fold(archive manifests + live assets) -> rolling archive entries
            + live releases API                     -> existence, size, download counts

Supports an array of repos as input, manifest checkout directory for rvb,
caching of API responses and manifests, and arbitrary downloadable artifact extensions.
"""
import argparse
import gzip
import importlib.util
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_REPOS = [
    "sharath-5br2r/apps",
    "sharath-5br2r/Eden-Workflow",
    "sharath-5br2r/Dolphin-Extra",
    "sharath-5br2r/LeviLaunchroid-Extra",
    "sharath-5br2r/ZalithLauncher2-Extra",
]

ARCH_ORDER = {"arm64": 0, "arm": 1, "all": 2, "universal": 3, "x86_64": 4, "x86": 5}
FILE_PREFIX_RE = re.compile(r"^(.*?)-(?:v[a-zA-Z0-9]|module-)", re.IGNORECASE)

DOWNLOADABLE_EXTENSIONS = (
    ".apk", ".apks", ".xapk", ".apkm",
    ".exe", ".msi",
    ".appimage", ".dmg", ".pkg", ".deb", ".rpm", ".flatpak", ".snap",
    ".zip", ".7z", ".rar", ".tgz", ".tar", ".tar.gz", ".tar.xz", ".tar.bz2", ".tar.zst",
)


def _ver_key(v):
    """Numeric-aware version sort key so 6.12.18 outranks 6.12.9; non-numeric
    segments (e.g. `1.42.1-dev.2`) fall back to their string form."""
    parts = re.split(r"[.\-]+", str(v))
    return [(0, int(p)) if p.isdigit() else (1, p) for p in parts]



def _load_rvb_naming():
    candidates = []
    # Local in same directory
    candidates.append(Path(__file__).resolve().parent / "naming.py")
    env = os.environ.get("RVB_NAMING_DIR")
    if env:
        candidates.append(Path(env) / "naming.py")
    candidates.append(Path(__file__).resolve().parents[3] /
                      "rvb" / ".github" / "scripts" / "naming.py")
    candidates.append(Path(__file__).resolve().parents[3] /
                      "patched-apks-builder-2nd" / ".github" / "scripts" / "naming.py")
    for path in candidates:
        if path.is_file():
            try:
                spec = importlib.util.spec_from_file_location("rvb_naming", str(path))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod
            except Exception as e:
                print(f"Warning: could not load rvb naming rules from {path}: {e}", file=sys.stderr)
    return None


_naming = _load_rvb_naming()


def _builtin_normalize_key(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _builtin_normalize_arch(arch_raw):
    a = (arch_raw or "").lower().strip()
    if "arm64" in a or "aarch64" in a:
        return "arm64"
    if "arm" in a or "armeabi" in a:
        return "arm"
    if a in ["all", "universal"] or a.endswith("-all") or a.endswith("-universal"):
        return "all"
    if "x86_64" in a or "x64" in a or "amd64" in a:
        return "x86_64"
    if "x86" in a:
        return "x86"
    return a or "all"


def _builtin_extract_arch(fname, version=""):
    match = re.search(
        r"-(arm64-v8a|armeabi-v7a|arm-v7a|aarch64|arm64|arm32|arm|x86_64|amd64|x64|x86|universal|all)(?:-(?:apk|module))?\.[a-zA-Z0-9.]+$",
        fname,
        re.IGNORECASE,
    )
    if match:
        return match.group(1)
    if version:
        clean_ver = re.escape(version.lstrip("v"))
        m = re.search(
            rf"-v?{clean_ver}-([a-zA-Z0-9_-]+?)(?:-(?:apk|module))?\.[a-zA-Z0-9.]+对手", fname, re.IGNORECASE) if False else re.search(
            rf"-v?{clean_ver}-([a-zA-Z0-9_-]+?)(?:-(?:apk|module))?\.[a-zA-Z0-9.]+$", fname, re.IGNORECASE)
        if m:
            return m.group(1)
    name_no_ext = fname.rsplit(".", 1)[0]
    name_no_mode = re.sub(r"-(?:apk|module)$", "", name_no_ext, flags=re.IGNORECASE)
    parts = name_no_mode.split("-")
    return parts[-1] if len(parts) > 1 else "all"


def _builtin_file_prefix(fname):
    m = FILE_PREFIX_RE.match(fname)
    return m.group(1) if m else fname.rsplit(".", 1)[0]


normalize_key = getattr(_naming, "normalize_key", _builtin_normalize_key) if _naming else _builtin_normalize_key
normalize_arch = getattr(_naming, "normalize_arch", _builtin_normalize_arch) if _naming else _builtin_normalize_arch
extract_arch = getattr(_naming, "extract_arch", _builtin_extract_arch) if _naming else _builtin_extract_arch
file_prefix = getattr(_naming, "file_prefix", _builtin_file_prefix) if _naming else _builtin_file_prefix


def extract_version(fname):
    """Extract version from filename: anything that starts with a v after a hyphen."""
    m = re.search(
        r"-(v[a-zA-Z0-9._-]+?)(?:-(?:arm64-v8a|armeabi-v7a|arm-v7a|aarch64|arm64|arm32|arm|x86_64|amd64|x64|x86|universal|all|[a-zA-Z0-9_]+))?\.[a-zA-Z0-9.]+$",
        fname,
        re.IGNORECASE,
    )
    if m:
        return m.group(1)
    m = re.search(r"-(v[a-zA-Z0-9._-]+)", fname, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def run_gh(args, check=True):
    result = subprocess.run(["gh"] + args, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"Error running gh {' '.join(args)}: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return result.stdout


def get_cache_path(cache_dir, repo, key):
    if not cache_dir:
        return None
    safe_repo = re.sub(r"[^a-zA-Z0-9_.-]", "_", repo)
    p = Path(cache_dir) / safe_repo / key
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def derive_metadata(fname, e, repo=None):
    app_key = e.get("appKey")
    app_name = e.get("appName")
    brand_key = e.get("brandKey")
    brand_name = e.get("brandName")
    variant = e.get("variant")
    sub_variant = e.get("subVariant")

    repo_lower = (repo or "").lower()

    if not app_key:
        if "eden" in repo_lower or fname.lower().startswith("eden"):
            app_key = "eden"
            app_name = app_name or "Eden"
        elif "dolphin" in repo_lower or fname.lower().startswith("dolphin"):
            app_key = "dolphin-extra"
            app_name = app_name or "Dolphin Extra"
        elif "levilaunchroid" in repo_lower or fname.lower().startswith("levilaunchroid"):
            app_key = "levilaunchroid-extra"
            app_name = app_name or "LeviLaunchroid Extra"
        elif "zalithlauncher" in repo_lower or fname.lower().startswith("zalithlauncher"):
            app_key = "zalithlauncher2-extra"
            app_name = app_name or "ZalithLauncher2 Extra"
        else:
            base = file_prefix(fname)
            app_key = normalize_key(base)
            app_name = app_name or base

    if not brand_key:
        if "eden" in app_key:
            brand_key = "eden"
            brand_name = brand_name or "Eden"
        elif "dolphin" in app_key:
            brand_key = "dolphin-extra"
            brand_name = brand_name or "Dolphin Extra"
        elif "levilaunchroid" in app_key:
            brand_key = "levilaunchroid-extra"
            brand_name = brand_name or "LeviLaunchroid Extra"
        elif "zalithlauncher" in app_key:
            brand_key = "zalithlauncher2-extra"
            brand_name = brand_name or "ZalithLauncher2 Extra"
        else:
            brand_key = "patched"
            brand_name = brand_name or "Patched"

    return app_key, app_name, brand_key, brand_name, variant, sub_variant


def fallback_entry(fname, origin_build, published_at, repo=None):
    name = file_prefix(fname)
    nl = fname.lower()
    file_type = "APK" if nl.endswith((".apk", ".apks", ".xapk", ".apkm")) else (
        "AppImage" if nl.endswith(".appimage") else (
            "DMG" if nl.endswith(".dmg") else (
                "EXE" if nl.endswith((".exe", ".msi")) else "Module"
            )
        )
    )
    extracted_ver = extract_version(fname)
    entry = {
        "name": name,
        "version": extracted_ver,
        "appKey": None,
        "appName": None,
        "arch": normalize_arch(extract_arch(fname, extracted_ver or "")),
        "fileType": file_type,
        "brandKey": None,
        "brandName": None,
        "variant": None,
        "subVariant": None,
        "packageName": None,
        "patchSources": [],
        "changelogs": [],
        "appliedPatches": [],
        "skippedPatches": [],
        "failedPatches": [],
        "removedPatches": [],
        "originBuild": origin_build,
        "publishedAt": published_at,
    }
    app_key, app_name, brand_key, brand_name, variant, sub_variant = derive_metadata(fname, entry, repo)
    entry["appKey"] = app_key
    entry["appName"] = app_name
    entry["brandKey"] = brand_key
    entry["brandName"] = brand_name
    entry["variant"] = variant
    entry["subVariant"] = sub_variant
    return entry


def fetch_releases(repo, cache_dir=None):
    cp = get_cache_path(cache_dir, repo, "releases.json") if cache_dir else None
    if cp and cp.exists():
        try:
            with open(cp, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {r["tag_name"]: r for r in data if not r.get("draft") and r.get("tag_name")}
        except Exception as e:
            print(f"Cache read error for {repo}: {e}, fetching fresh.")

    raw = run_gh(["api", "--paginate", f"repos/{repo}/releases?per_page=100"], check=False)
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            return {}
        if cp:
            try:
                with open(cp, "w", encoding="utf-8") as f:
                    json.dump(data, f)
            except Exception:
                pass
        return {r["tag_name"]: r for r in data if not r.get("draft") and r.get("tag_name")}
    except Exception as e:
        print(f"Error parsing releases for {repo}: {e}", file=sys.stderr)
        return {}


def fetch_manifest(repo, tag, rel, cache_dir=None):
    cp = get_cache_path(cache_dir, repo, f"manifest_{tag}.json") if cache_dir else None
    if cp and cp.exists():
        try:
            with open(cp, "r", encoding="utf-8") as f:
                m = json.load(f)
            if isinstance(m, dict) and str(m.get("schema")) == "1" and isinstance(m.get("files"), dict):
                return m, None
        except Exception:
            pass

    asset = next((a for a in rel.get("assets", []) if a["name"] == "build.json"), None)
    if asset is None:
        return None, None
    api_url = asset["url"].replace("https://api.github.com/", "")
    raw = ""
    for attempt in range(1, 4):
        raw = run_gh(["api", api_url, "-H", "Accept: application/octet-stream"], check=False)
        if raw.strip():
            break
        if attempt < 3:
            import time
            time.sleep(2 * attempt)
    if not raw.strip():
        return None, f"could not download build.json for {tag} in {repo}"
    try:
        m = json.loads(raw)
        if not isinstance(m, dict):
            raise ValueError("manifest is not a dict")
        if str(m.get("schema")) != "1" or not isinstance(m.get("files"), dict):
            raise ValueError("manifest must be schema 1 with a 'files' dictionary; raw JSON manifests are rejected")

        if cp:
            try:
                with open(cp, "w", encoding="utf-8") as f:
                    json.dump(m, f)
            except Exception:
                pass
        return m, None
    except Exception as e:
        return None, f"build.json for {tag} in {repo} is invalid: {e}"


def manifest_from_dir(manifest_dir, tag):
    """Load one manifest from tree (same return contract as fetch_manifest)."""
    md = Path(manifest_dir)
    if tag in ("stable", "beta"):
        p = md / "manifests" / "archive" / f"{tag}.json"
    else:
        p = md / "manifests" / f"{tag}.json"
    if not p.is_file():
        return None, None
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(m, dict) or not isinstance(m.get("files"), dict):
            raise ValueError("missing files map")
        return m, None
    except Exception as e:
        return None, f"{p} is not a valid manifest: {e}"


def fetch_all_manifests(repo, releases, tags, max_workers=6, cache_dir=None, manifest_dir=None):
    """Pre-fetch build.json manifests for tags concurrently or from manifest_dir."""
    if manifest_dir:
        res = {}
        missing = []
        for tag in tags:
            m, err = manifest_from_dir(manifest_dir, tag)
            if m is not None:
                res[tag] = (m, None)
            else:
                missing.append(tag)
        if not missing:
            return res
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            fallback = {
                tag: fut.result()
                for tag, fut in (
                    (tag, pool.submit(fetch_manifest, repo, tag, releases[tag], cache_dir))
                    for tag in missing
                )
            }
        res.update(fallback)
        return res

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return {
            tag: fut.result()
            for tag, fut in (
                (tag, pool.submit(fetch_manifest, repo, tag, releases[tag], cache_dir))
                for tag in tags
            )
        }


def live_downloadable_assets(rel):
    """name -> asset dict for downloadable files (never manifest or checksums)."""
    res = {}
    for a in rel.get("assets", []):
        name = a["name"]
        nl = name.lower()
        if nl.endswith((".json", ".zsync", ".sha256", ".sha1", ".md5", ".asc", ".sig", ".txt", ".log")):
            continue
        if any(nl.endswith(ext) for ext in DOWNLOADABLE_EXTENSIONS):
            res[name] = a
    return res


class Catalog:
    def __init__(self):
        self.apps = {}       # appKey -> app entry
        self.order = []      # appKeys in creation order
        self.now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def app(self, app_key, app_name):
        if app_key not in self.apps:
            entry = {
                "appKey": app_key,
                "appName": app_name or app_key,
                "totalDownloads": 0,
                "latestPublishedAt": self.now_iso,
                "brands": [],
            }
            self.apps[app_key] = entry
            self.order.append(app_key)
        else:
            entry = self.apps[app_key]
            if app_name:
                entry["appName"] = app_name
        return self.apps[app_key]

    def brand(self, app_entry, brand_key, brand_name):
        entry = next((x for x in app_entry["brands"] if x["brandKey"] == brand_key), None)
        if entry is None:
            entry = {
                "brandKey": brand_key,
                "brandName": brand_name,
                "latestVersion": "",
                "latestPublishedAt": self.now_iso,
                "totalDownloads": 0,
                "variants": [],
                "builds": [],
            }
            app_entry["brands"].append(entry)
        if brand_name:
            entry["brandName"] = brand_name
        return entry

    def variant(self, brand_entry, variant, sub_variant, prefix, package_name):
        v = next(
            (x for x in brand_entry["variants"]
             if x.get("variant") == variant and x.get("subVariant") == sub_variant),
            None,
        )
        if v is None:
            v = {
                "variant": variant,
                "subVariant": sub_variant,
                "packageName": package_name or "",
                "apkFilter": f"^{prefix}-v.*\\.apk$" if prefix else "",
                "latestStable": None,
                "latestBeta": None,
            }
            brand_entry["variants"].append(v)
        if package_name:
            v["packageName"] = package_name
        if prefix and not v.get("apkFilter"):
            v["apkFilter"] = f"^{prefix}-v.*\\.apk$"
        return v


def group_files(manifest, live_assets, tag, rel, is_archive, repo=None):
    entries = manifest["files"] if (manifest and isinstance(manifest.get("files"), dict)) else {}
    groups = {}
    for fname, e in entries.items():
        if live_assets.get(fname) is None:
            continue
        app_key, app_name, brand_key, brand_name, variant, sub_variant = derive_metadata(fname, e, repo)
        ver = e.get("version") or extract_version(fname)
        gk = (
            app_key,
            app_name,
            brand_key,
            brand_name,
            variant,
            sub_variant,
            # A numbered release is ONE build card keyed by the tag; the app
            # version is per-file (a fallback arch can differ from arm64), so it
            # must not split the card. The archive release is a version history,
            # so there the version stays part of the card identity.
            (e.get("version") or ver) if is_archive else None,
        )
        groups.setdefault(gk, []).append((fname, e))

    covered = set(entries.keys())
    uncovered = [fname for fname in live_assets if fname not in covered]
    if uncovered:
        pub = (rel.get("published_at") or "").replace("+00:00", "Z")
        for fname in uncovered:
            fb = fallback_entry(fname, None if is_archive else tag, pub, repo)
            gk = (
                fb["appKey"],
                fb["appName"],
                fb["brandKey"],
                fb["brandName"],
                fb["variant"],
                fb["subVariant"],
                fb.get("version") if is_archive else None,
            )
            groups.setdefault(gk, []).append((fname, fb))
    return groups


def build_assets(group, live_assets):
    assets = []
    for fname, e in group:
        live = live_assets[fname]
        raw_arch = e.get("arch") or extract_arch(fname, e.get("version") or "")
        asset = {
            "name": fname,
            "browser_download_url": live["browser_download_url"],
            "size": live.get("size", 0),
            "download_count": live.get("download_count", 0),
            "arch": normalize_arch(raw_arch),
            # Per-file truth: a numbered build can hold several versions, so each
            # asset names its own; appliedPatches is carried inline here and folded
            # into the shared patchSets table (as a per-asset patchSetRef) in finalize.
            "version": e.get("version") or "",
            "appliedPatches": e.get("appliedPatches") or [],
            # fileType intentionally omitted: it is always derivable from the
            # asset name (.apk -> APK, .zip -> Module) and computed client-side.
        }
        for field in ("minSdk", "versionCode", "densities", "nativeLibraries"):
            val = e.get(field)
            if val is not None:
                asset[field] = val
        assets.append(asset)
    assets.sort(key=lambda a: ARCH_ORDER.get(a["arch"], 99))
    return assets


def apply_numbered(cat, repo, tag, rel, manifest):
    meta = (manifest or {}).get("meta") or {}
    channel = meta.get("channel")
    release_type = channel if channel in ("stable", "beta") else (
        "beta" if rel.get("prerelease") else "stable"
    )
    build_id = meta.get("build") or tag
    published_at = meta.get("publishedAt") or (
        rel.get("published_at") or "").replace("+00:00", "Z")
    live_assets = live_downloadable_assets(rel)
    groups = group_files(manifest, live_assets, tag, rel, is_archive=False, repo=repo)
    for (app_key, app_name, brand_key, brand_name, variant, sub_variant, _version), group in groups.items():
        e0 = next((e for _, e in group if e.get("appliedPatches") or e.get("patchSources") or e.get("changelogs") or e.get("changelogUrls") or e.get("skippedPatches") or e.get("failedPatches") or e.get("removedPatches")), group[0][1])
        # Distinct versions across this card's files, newest first. `version` is
        # the primary (highest) for back-compat (latestVersion, channel pointers);
        # `versions` lets the UI show every version one build actually published.
        vers = sorted({(e.get("version") or "")
                      for _, e in group if e.get("version")}, key=_ver_key, reverse=True)
        version = vers[0] if vers else ""
        prefix = next((e.get("name") for _, e in group if e.get("name")), "")
        pkg = next((e.get("packageName") for _, e in group if e.get("packageName")), "")
        app_entry = cat.app(app_key, app_name)
        brand_entry = cat.brand(app_entry, brand_key, brand_name or "Patched")
        cat.variant(brand_entry, variant, sub_variant, prefix, pkg)
        build_version = version or next((e.get("version") for _, e in group if e.get("version")), "")
        if not build_version or len(build_version) > 50 or " " in build_version:
            fname_ver = next((extract_version(fn) for fn, _ in group if extract_version(fn)), None)
            if fname_ver:
                build_version = fname_ver
            elif tag and (tag.startswith("v") or "pr" in tag.lower()):
                build_version = tag
            else:
                build_version = build_version or str(build_id)
        skipped_patches = next((e.get("skippedPatches") for _, e in group if e.get("skippedPatches")), []) or []
        failed_patches = next((e.get("failedPatches") for _, e in group if e.get("failedPatches")), []) or []
        removed_patches = next((e.get("removedPatches") or e.get("excludedPatches") for _, e in group if e.get("removedPatches") or e.get("excludedPatches")), []) or []
        build_entry = {
            "build": build_id,
            "releaseId": tag,
            "releaseType": release_type,
            "isArchive": False,
            "version": build_version,
            "versions": vers,
            "variant": variant,
            "subVariant": sub_variant,
            "publishedAt": published_at,
            "releaseUrl": f"https://github.com/{repo}/releases/tag/{tag}",
            "patchSources": e0.get("patchSources") or (e0.get("patches").split() if isinstance(e0.get("patches"), str) else []),
            "changelogs": e0.get("changelogs") or e0.get("changelogUrls") or (e0.get("changelog") if isinstance(e0.get("changelog"), list) else ([e0.get("changelog")] if e0.get("changelog") else [])),
            "appliedPatches": e0.get("appliedPatches") or [],
            "skippedPatches": skipped_patches,
            "failedPatches": failed_patches,
            "removedPatches": removed_patches,
            "assets": build_assets(group, live_assets),
        }
        existing_build = next(
            (b for b in brand_entry["builds"]
             if not b.get("isArchive") and str(b.get("build")) == str(build_id)
             and b.get("variant") == variant and b.get("subVariant") == sub_variant),
            None
        )
        if existing_build and existing_build.get("releaseId") == tag:
            existing_asset_names = {a["name"] for a in existing_build.get("assets", [])}
            for a in build_entry["assets"]:
                if a["name"] not in existing_asset_names:
                    existing_build["assets"].append(a)
                    existing_asset_names.add(a["name"])
            existing_build["assets"].sort(key=lambda a: ARCH_ORDER.get(a["arch"], 99))
            if not existing_build.get("appliedPatches") and build_entry.get("appliedPatches"):
                existing_build["appliedPatches"] = build_entry["appliedPatches"]
            if not existing_build.get("patchSources") and build_entry.get("patchSources"):
                existing_build["patchSources"] = build_entry["patchSources"]
            if not existing_build.get("changelogs") and build_entry.get("changelogs"):
                existing_build["changelogs"] = build_entry["changelogs"]
            if not existing_build.get("skippedPatches") and build_entry.get("skippedPatches"):
                existing_build["skippedPatches"] = build_entry["skippedPatches"]
            if not existing_build.get("failedPatches") and build_entry.get("failedPatches"):
                existing_build["failedPatches"] = build_entry["failedPatches"]
            if not existing_build.get("removedPatches") and build_entry.get("removedPatches"):
                existing_build["removedPatches"] = build_entry["removedPatches"]
            if not existing_build.get("version") and build_entry.get("version"):
                existing_build["version"] = build_entry["version"]
        else:
            brand_entry["builds"] = [
                b for b in brand_entry["builds"]
                if b.get("isArchive") or not (
                    str(b.get("build")) == str(build_id) and b.get("variant") == variant and b.get("subVariant") == sub_variant
                )
            ]
            brand_entry["builds"].insert(0, build_entry)


def apply_archive(cat, repo, tag, rel, manifest):
    meta = (manifest or {}).get("meta") or {}
    channel = meta.get("channel")
    release_type = channel if channel in ("stable", "beta") else (
        "beta" if tag == "beta" else "stable"
    )
    live_assets = live_downloadable_assets(rel)
    groups = group_files(manifest, live_assets, tag, rel, is_archive=True, repo=repo)
    for (app_key, app_name, brand_key, brand_name, variant, sub_variant, version), group in groups.items():
        e0 = next((e for _, e in group if e.get("appliedPatches") or e.get("patchSources") or e.get("changelogs") or e.get("changelogUrls") or e.get("skippedPatches") or e.get("failedPatches") or e.get("removedPatches")), group[0][1])
        prefix = next((e.get("name") for _, e in group if e.get("name")), "")
        pkg = next((e.get("packageName") for _, e in group if e.get("packageName")), "")
        published_at = max((e.get("publishedAt") or "" for _, e in group), default="") \
            or meta.get("publishedAt") or (rel.get("published_at") or "").replace("+00:00", "Z")
        app_entry = cat.app(app_key, app_name)
        brand_entry = cat.brand(app_entry, brand_key, brand_name or "Patched")
        cat.variant(brand_entry, variant, sub_variant, prefix, pkg)
        skipped_patches = next((e.get("skippedPatches") for _, e in group if e.get("skippedPatches")), []) or []
        failed_patches = next((e.get("failedPatches") for _, e in group if e.get("failedPatches")), []) or []
        removed_patches = next((e.get("removedPatches") or e.get("excludedPatches") for _, e in group if e.get("removedPatches") or e.get("excludedPatches")), []) or []
        archive_entry = {
            "build": version or tag,
            "releaseId": tag,
            "releaseType": release_type,
            "isArchive": True,
            "version": version or "",
            "variant": variant,
            "subVariant": sub_variant,
            "publishedAt": published_at,
            "releaseUrl": f"https://github.com/{repo}/releases/tag/{tag}",
            "patchSources": e0.get("patchSources") or (e0.get("patches").split() if isinstance(e0.get("patches"), str) else []),
            "changelogs": e0.get("changelogs") or e0.get("changelogUrls") or (e0.get("changelog") if isinstance(e0.get("changelog"), list) else ([e0.get("changelog")] if e0.get("changelog") else [])),
            "appliedPatches": e0.get("appliedPatches") or [],
            "skippedPatches": skipped_patches,
            "failedPatches": failed_patches,
            "removedPatches": removed_patches,
            "assets": build_assets(group, live_assets),
        }
        brand_entry["builds"] = [
            b for b in brand_entry["builds"]
            if not (
                b.get("isArchive") and b.get("releaseId") == tag and b.get("version") == version
                and b.get("variant") == variant and b.get("subVariant") == sub_variant
                and b.get("releaseType") == release_type
            )
        ]
        insert_at = len(brand_entry["builds"]) - sum(1 for b in brand_entry["builds"] if b.get("isArchive"))
        brand_entry["builds"].insert(insert_at, archive_entry)


def _dedup_lists(builds, field, ref_key, table):
    index = {}
    for build in builds:
        val = build.pop(field, None)
        if not val:
            continue
        key = json.dumps(val, ensure_ascii=False, separators=(",", ":"))
        idx = index.get(key)
        if idx is None:
            idx = len(table)
            table.append(val)
            index[key] = idx
        build[ref_key] = idx


def finalize(cat):
    apps = []
    for app_key in cat.order:
        app_entry = cat.apps[app_key]
        surviving_brands = []
        for brand in app_entry["brands"]:
            builds = sorted(brand["builds"], key=lambda b: b.get("publishedAt") or "", reverse=True)
            if not builds:
                continue
            brand["builds"] = builds
            brand["latestVersion"] = builds[0].get("version", "")
            brand["latestPublishedAt"] = builds[0].get("publishedAt", "")
            brand["totalDownloads"] = sum(
                sum(a.get("download_count", 0) for a in b.get("assets", [])) for b in builds
            )
            surviving_variants = []
            for v in brand["variants"]:
                v_var, v_sub = v.get("variant"), v.get("subVariant")
                v_builds = [b for b in builds if b.get("variant") == v_var and b.get("subVariant") == v_sub]
                if not v_builds:
                    continue
                for ch in ("latestStable", "latestBeta"):
                    rel_filter = "stable" if ch == "latestStable" else "beta"
                    newest = next((b for b in v_builds if b.get("releaseType") == rel_filter), None)
                    v[ch] = newest.get("build", "") if newest else None
                surviving_variants.append(v)
            brand["variants"] = surviving_variants
            surviving_brands.append(brand)
        if surviving_brands:
            app_entry["brands"] = surviving_brands
            newest = max((b.get("publishedAt", "") for br in surviving_brands for b in br["builds"]), default="")
            app_entry["latestPublishedAt"] = newest
            app_entry["totalDownloads"] = sum(b.get("totalDownloads", 0) for b in surviving_brands)
            apps.append(app_entry)
    apps.sort(key=lambda a: a["appName"].lower())

    all_builds = [build for app in apps for brand in app["brands"] for build in brand["builds"]]
    for build in all_builds:
        if build.get("releaseId") is not None and build.get("releaseId") == build.get("build"):
            build.pop("releaseId")

    patch_sets, changelog_sets, patch_source_sets = [], [], []
    skipped_patch_sets, failed_patch_sets, removed_patch_sets = [], [], []
    _dedup_lists(all_builds, "appliedPatches", "patchSetRef", patch_sets)
    _dedup_lists(all_builds, "changelogs", "changelogRef", changelog_sets)
    _dedup_lists(all_builds, "patchSources", "patchSourceRef", patch_source_sets)
    _dedup_lists(all_builds, "skippedPatches", "skippedPatchSetRef", skipped_patch_sets)
    _dedup_lists(all_builds, "failedPatches", "failedPatchSetRef", failed_patch_sets)
    _dedup_lists(all_builds, "removedPatches", "removedPatchSetRef", removed_patch_sets)

    # Per-arch applied patches: each asset carries the list its own file applied
    # (a fallback arch can differ). Fold those into the SAME patchSets table so a
    # list identical to another collapses to a shared index (no duplication), while
    # a genuinely different one gets its own — the UI then shows per-arch tabs only
    # where the asset refs actually differ.
    all_assets = [a for build in all_builds for a in build.get("assets", [])]
    _dedup_lists(all_assets, "appliedPatches", "patchSetRef", patch_sets)

    return {
        "version": 2,
        "updated_at": cat.now_iso,
        "patchSets": patch_sets,
        "changelogSets": changelog_sets,
        "patchSourceSets": patch_source_sets,
        "skippedPatchSets": skipped_patch_sets,
        "failedPatchSets": failed_patch_sets,
        "removedPatchSets": removed_patch_sets,
        "apps": apps,
    }


def validate(catalog, existing_path, ignore_existing=False):
    if ignore_existing or os.environ.get("FORCE") == "1":
        print("Ignoring existing data.json / circuit breaker skipped.")
        return
    if not existing_path or not Path(existing_path).exists():
        return
    try:
        old = json.load(open(existing_path, encoding="utf-8"))
    except Exception:
        print("Warning: existing data.json unreadable; skipping shrink check.")
        return
    old_apps = len(old.get("apps", []))
    new_apps = len(catalog["apps"])
    old_builds = sum(len(b["builds"]) for a in old.get("apps", []) for b in a.get("brands", []))
    new_builds = sum(len(b["builds"]) for a in catalog["apps"] for b in a.get("brands", []))
    ratio = float(os.environ.get("MIN_RATIO", "0.6"))
    print(f"Circuit breaker: apps {new_apps}/{old_apps}, builds {new_builds}/{old_builds} (min ratio {ratio})")
    if old_apps and (new_apps < old_apps * ratio or new_builds < old_builds * ratio):
        print("Error: rebuilt catalog shrank beyond the safety threshold. Refusing to write.", file=sys.stderr)
        sys.exit(2)


def main():
    ap = argparse.ArgumentParser(description="Rebuild catalog data.json from releases")
    ap.add_argument(
        "--repos", "--repo",
        nargs="*",
        default=None,
        dest="repos",
        help="One or more GitHub repositories (owner/repo). Defaults to all 5 repos."
    )
    ap.add_argument("--rvb-repo", default=os.environ.get("RVB_REPO", "sharath-5br2r/apps"),
                    help="rvb repository name that uses manifest-dir")
    ap.add_argument("--manifest-dir", default=None,
                    help="checkout of rvb's website branch; when set, manifests for rvb "
                         "are read from disk instead of release assets")
    ap.add_argument("--out", default="data.json", help="Output path for data.json")
    ap.add_argument("--existing", default=None, help="Existing data.json for shrink checks")
    ap.add_argument("--ignore-existing", action="store_true", help="Ignore existing data.json (skip circuit breaker)")
    ap.add_argument("--cache-dir", default=".cache", help="Directory to cache API responses and manifests")
    ap.add_argument("--no-cache", action="store_true", help="Disable caching")
    ap.add_argument("--no-gzip", action="store_true", help="Do not write data.json.gz")
    args = ap.parse_args()

    repos = args.repos
    if not repos:
        env_repo = os.environ.get("RVB_REPO")
        if env_repo and "," in env_repo:
            repos = [r.strip() for r in env_repo.split(",") if r.strip()]
        else:
            repos = DEFAULT_REPOS

    cache_dir = None if args.no_cache else args.cache_dir
    cat = Catalog()

    default_manifest_dir = args.manifest_dir
    if not default_manifest_dir:
        cwd_manifests = Path("manifests")
        if cwd_manifests.is_dir():
            default_manifest_dir = "."
        else:
            repo_root_manifests = Path(__file__).resolve().parents[2] / "manifests"
            if repo_root_manifests.is_dir():
                default_manifest_dir = str(repo_root_manifests.parent)

    for repo in repos:
        print(f"\n--- Processing repository: {repo} ---")
        releases = fetch_releases(repo, cache_dir=cache_dir)
        if not releases:
            print(f"Warning: no releases found for {repo}, skipping.")
            continue
        print(f"Found {len(releases)} releases for {repo}.")

        numbered_tags = sorted(
            (t for t in releases if t not in ("stable", "beta")),
            key=lambda t: (len(t), t),
        )
        all_tags = numbered_tags + [t for t in ("stable", "beta") if t in releases]

        repo_manifest_dir = default_manifest_dir if (default_manifest_dir and (repo == args.rvb_repo or "rvb" in repo.lower())) else None
        fetched = fetch_all_manifests(repo, releases, all_tags, max_workers=6, cache_dir=cache_dir, manifest_dir=repo_manifest_dir)

        missing_manifests = []
        for tag in numbered_tags:
            rel = releases[tag]
            m = fetched.get(tag, (None, None))[0]
            if m is None:
                missing_manifests.append(tag)
            apply_numbered(cat, repo, tag, rel, m)

        for tag in ("stable", "beta"):
            if tag not in releases:
                continue
            rel = releases[tag]
            m = fetched.get(tag, (None, None))[0]
            if m is None:
                missing_manifests.append(tag)
            apply_archive(cat, repo, tag, rel, m)

        if missing_manifests:
            print(f"Note: {len(missing_manifests)} releases in {repo} had no build.json (fallback entries used)")

    catalog = finalize(cat)
    validate(catalog, args.existing, ignore_existing=args.ignore_existing or (args.existing is None))

    out_path = Path(args.out)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, separators=(",", ":"))

    total_builds = sum(len(b["builds"]) for a in catalog["apps"] for b in a["brands"])
    total_assets = sum(len(b["assets"]) for a in catalog["apps"] for b in a["brands"] for b in b["builds"])
    print(f"\nWrote {out_path}: {len(catalog['apps'])} apps, {total_builds} build entries, {total_assets} assets.")

    if not args.no_gzip:
        gz_path = out_path.with_suffix(out_path.suffix + ".gz")
        with open(out_path, "rb") as f_in, gzip.open(gz_path, "wb", compresslevel=9) as f_out:
            f_out.write(f_in.read())
        print(f"Wrote {gz_path} ({gz_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
