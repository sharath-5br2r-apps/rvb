#!/usr/bin/env python3
"""Merge parallel fetched_app_versions_*.json artifacts into a single fetched_app_versions.json.

Also merges check_list_*.txt into check_list.txt if present.
"""

from __future__ import annotations

import glob
import json
import os
import sys

def main() -> int:
    output_file = os.environ.get("FETCHED_APP_VERSIONS_FILE", "fetched_app_versions.json")
    pattern = os.environ.get("FETCHED_PATTERN", "fetched_app_versions_*.json")
    
    merged: dict[str, any] = {}
    
    files = sorted(glob.glob(pattern))
    if not files:
        # Fallback to direct search in artifacts subdirs or current dir
        files = sorted(glob.glob("**/fetched_app_versions*.json", recursive=True))
        # Exclude final output file itself if it matches
        files = [f for f in files if os.path.basename(f) != os.path.basename(output_file)]

    print(f"Found {len(files)} fetched version chunk files to merge: {files}")
    
    for fpath in files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    continue
                data = json.loads(content)
                if isinstance(data, dict):
                    merged.update(data)
                    print(f"  Merged {len(data)} entries from {fpath}")
        except Exception as e:
            print(f"  Warning: failed to read {fpath}: {e}", file=sys.stderr)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Successfully wrote {len(merged)} total app versions to {output_file}")

    # Merge check_list if present
    check_lists = sorted(glob.glob("**/check_list*.txt", recursive=True))
    check_lists = [c for c in check_lists if os.path.abspath(c) != os.path.abspath("check_list.txt")]
    if check_lists:
        seen = set()
        merged_lines = []
        for cl in check_lists:
            try:
                with open(cl, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and line not in seen:
                            seen.add(line)
                            merged_lines.append(line)
            except Exception:
                pass
        with open("check_list.txt", "w", encoding="utf-8") as f:
            for line in merged_lines:
                f.write(f"{line}\n")
        print(f"Merged {len(merged_lines)} lines into check_list.txt")

    return 0

if __name__ == "__main__":
    sys.exit(main())
