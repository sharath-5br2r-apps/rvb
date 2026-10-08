#!/usr/bin/env python3
"""Aggregate all build part logs, markdowns, and JSON logs into a unified summary."""

from __future__ import annotations

import glob
import json
import os
import sys
from typing import Any, Dict, List

def load_jsonl(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return []
    entries: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    obj = json.loads(stripped)
                    if isinstance(obj, dict):
                        entries.append(obj)
                    elif isinstance(obj, list):
                        entries.extend(x for x in obj if isinstance(x, dict))
                except Exception:
                    continue
        return entries
    except Exception:
        return []

# Backwards compatible alias
load_json = load_jsonl

def main() -> int:
    # 1. Locate all downloaded logs or artifacts
    search_dirs = ["logs_artifacts", "part_logs", "artifacts", "."]
    
    # Locate build_log.jsonl
    found_build_log_jsons = glob.glob("**/build_log.jsonl", recursive=True)

    all_entries: List[Dict[str, Any]] = []

    for bl in found_build_log_jsons:
        if "aggregated_out" in bl:
            continue
        data = load_json(bl)
        if isinstance(data, list):
            all_entries.extend(data)

    # Deduplicate entries
    deduped = []
    seen = set()
    for e in all_entries:
        key = (e.get("timestamp"), e.get("level"), e.get("app"), e.get("part"), e.get("message"))
        if key not in seen:
            seen.add(key)
            deduped.append(e)

    # Import formatter from generate_error_markdown
    sys.path.insert(0, os.path.dirname(__file__))
    import generate_error_markdown

    global_summary = generate_error_markdown.format_report(deduped)

    # Build per-artifact error log sections
    per_artifact_sections: List[str] = []
    
    # Find all build_log.md, error.md, or log files grouped by directory / artifact
    artifact_dirs = set()
    for f in glob.glob("**/*", recursive=True):
        if os.path.isfile(f) and (os.path.basename(f) in ["build_log.md", "error.md", "build_log.jsonl", "error.log"]):
            d = os.path.dirname(f)
            if d and d != "." and not d.startswith("aggregated_out"):
                artifact_dirs.add(d)

    for ad in sorted(artifact_dirs):
        artifact_name = os.path.basename(ad)
        section_lines = [f"### 📁 Artifact / Job: `{artifact_name}`\n"]
        
        # Check if build_log.md / error.md exists
        blmd = os.path.join(ad, "build_log.md")
        emd = os.path.join(ad, "error.md")
        bljl = os.path.join(ad, "build_log.jsonl")
        el = os.path.join(ad, "error.log")
        
        has_content = False
        entries_in_part = []
        if os.path.exists(bljl):
            d = load_json(bljl)
            if isinstance(d, list):
                entries_in_part.extend(d)
            
        if entries_in_part:
            part_deduped = []
            pseen = set()
            for e in entries_in_part:
                k = (e.get("timestamp"), e.get("level"), e.get("app"), e.get("part"), e.get("message"))
                if k not in pseen:
                    pseen.add(k)
                    part_deduped.append(e)
            part_md = generate_error_markdown.format_report(part_deduped)
            section_lines.append(part_md)
            has_content = True
        elif os.path.exists(blmd) and os.path.getsize(blmd) > 0:
            with open(blmd, "r", encoding="utf-8") as f:
                section_lines.append(f.read())
            has_content = True
        elif os.path.exists(emd) and os.path.getsize(emd) > 0:
            with open(emd, "r", encoding="utf-8") as f:
                section_lines.append(f.read())
            has_content = True
        elif os.path.exists(el) and os.path.getsize(el) > 0:
            with open(el, "r", encoding="utf-8") as f:
                raw_log = f.read().strip()
                if raw_log:
                    section_lines.append(f"```text\n{raw_log}\n```\n")
                    has_content = True

        if has_content:
            per_artifact_sections.append("\n".join(section_lines))

    # Combine into full summary
    out_lines = []
    out_lines.append("# 🏁 Final Build Workflow Summary\n")
    out_lines.append(global_summary)
    out_lines.append("\n")

    final_content = "\n".join(out_lines) + "\n"

    out_file = sys.argv[1] if len(sys.argv) > 1 else "workflow_summary.md"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(final_content)

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write(final_content)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
