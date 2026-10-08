#!/bin/bash
set -euo pipefail

# Prune orphaned per-build manifests from the `website` branch: when the
# Cleanup workflow deletes a numbered release, its manifests/<tag>.json goes
# too (same pattern as cleanup_update_branch.sh applies to changelogs on the
# update branch). The cumulative archive/*.json files are never touched here —
# entries for pruned archive assets drop out at the next build's merge via the
# live-asset filter.
#
# Env: GITHUB_TOKEN (via default checkout credentials for git push).

echo "--- Fetching active releases ---"
ACTIVE_TAGS=$(gh release list -L 200 --json tagName -q '.[].tagName' 2>/dev/null || true)

ORIG_REF=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || git rev-parse HEAD 2>/dev/null || echo "main")
cleanup() {
  echo "--- Restoring original branch ($ORIG_REF) ---"
  git checkout "$ORIG_REF" 2>/dev/null || git checkout main 2>/dev/null || true
}
trap cleanup EXIT

echo "--- Checking out website branch ---"
if ! git ls-remote --exit-code --heads origin website >/dev/null 2>&1; then
  echo "No website branch on origin — nothing to prune."
  exit 0
fi
git fetch origin website
git checkout -B website origin/website

DELETED_COUNT=0
if [ -d manifests ]; then
  echo "--- Checking manifests directory ---"
  shopt -s nullglob
  if [ -z "$ACTIVE_TAGS" ]; then
    echo "No active releases — wiping all manifests."
    for f in manifests/*.json; do
      [ -f "$f" ] || continue
      echo "Deleting: $f"
      rm -f "$f"
      DELETED_COUNT=$((DELETED_COUNT + 1))
    done
    if [ -d archive ]; then
      echo "No active releases — wiping archive manifests."
      for f in archive/*.json; do
        [ -f "$f" ] || continue
        echo "Deleting: $f"
        rm -f "$f"
        DELETED_COUNT=$((DELETED_COUNT + 1))
      done
    fi
  else
    for f in manifests/*.json; do
      [ -f "$f" ] || continue
      tag=$(basename "$f" .json)
      if ! echo "$ACTIVE_TAGS" | grep -Fxq "$tag"; then
        echo "Pruning orphaned manifest: $f (release tag '$tag' no longer exists)"
        rm -f "$f"
        DELETED_COUNT=$((DELETED_COUNT + 1))
      fi
    done
  fi
  shopt -u nullglob
fi

echo "Pruned $DELETED_COUNT orphaned manifest(s)."

if ! git diff --quiet || ! git diff --cached --quiet || [ -n "$(git status --porcelain)" ]; then
  echo "--- Committing and pushing cleaned website branch ---"
  git config user.name "github-actions[bot]"
  git config user.email "github-actions[bot]@users.noreply.github.com"
  git add -A
  git commit -m "chore: prune orphaned manifests on website branch [skip ci]"
  git push origin website
else
  echo "No orphaned manifests to prune. Website branch is clean."
fi
