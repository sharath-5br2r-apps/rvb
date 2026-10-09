#!/bin/bash
set -euo pipefail

# Commit module updater pointers (stable/*.json, beta/*.json) and release
# changelogs (changelogs/<tag>.md) to the orphan `update` branch.
#
# Plumbing-only by design: builds the commit using a temporary git index and
# git commit-tree against the remote `update` branch head, never touching the
# checked-out branch, the working tree, or git index of the main repository.
# This prevents leaking repository files (.github, scripts, configs, etc.) or
# build artifacts into the update branch.

BRANCH="update"
TARGET_DIRS=("stable" "beta" "changelogs")
NEXT_VER_CODE="${NEXT_VER_CODE:-${1:-}}"
COMMIT_MSG="Bump version ${NEXT_VER_CODE}"

if [ -z "$NEXT_VER_CODE" ]; then
	echo "FATAL: NEXT_VER_CODE is required to commit to $BRANCH branch." >&2
	exit 1
fi

export GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-github-actions[bot]}"
export GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}"
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME"
export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"

# build_commit <base> — creates a commit on <base> carrying the worktree's
# updater files; echoes the new sha, returns 1 when nothing differs.
build_commit() {
	local base=${1:-} d idx tree blob old changed="" commit
	idx=$(mktemp)
	rm -f "$idx"
	if [ -n "$base" ]; then
		GIT_INDEX_FILE=$idx git read-tree "$base"
	else
		GIT_INDEX_FILE=$idx git read-tree --empty
	fi
	for d in "${TARGET_DIRS[@]}"; do
		[ -d "$d" ] || continue
		while IFS= read -r -d '' f; do
			blob=$(git hash-object -w "$f")
			if [ -n "$base" ]; then
				old=$(git rev-parse "$base:$f" 2> /dev/null || echo '')
				[ "$blob" = "$old" ] && continue
			fi
			GIT_INDEX_FILE=$idx git update-index --add --cacheinfo "100644,$blob,$f"
			changed=1
		done < <(find "$d" -type f \( -name '*.json' -o -name '*.md' \) -print0)
	done
	if [ -z "$changed" ]; then
		rm -f "$idx"
		return 1
	fi
	tree=$(GIT_INDEX_FILE=$idx git write-tree)
	rm -f "$idx"
	if [ -n "$base" ]; then
		commit=$(git commit-tree "$tree" -p "$base" -m "$COMMIT_MSG")
	else
		commit=$(git commit-tree "$tree" -m "$COMMIT_MSG")
	fi
	echo "$commit"
}

has_remote_branch=0
if git fetch -q origin "$BRANCH" 2>/dev/null; then
	has_remote_branch=1
fi

for attempt in 1 2 3 4 5; do
	base=""
	if [ "$has_remote_branch" -eq 1 ]; then
		base=$(git rev-parse FETCH_HEAD 2>/dev/null || echo '')
	fi

	if ! new=$(build_commit "$base"); then
		echo "No updater or changelog changes to commit to $BRANCH."
		exit 0
	fi

	if git push origin "$new:refs/heads/$BRANCH" 2>/dev/null; then
		echo "Pushed $new to $BRANCH."
		exit 0
	fi

	echo "Push attempt $attempt failed (concurrent update?); re-fetching and retrying..."
	sleep 3
	if git fetch -q origin "$BRANCH" 2>/dev/null; then
		has_remote_branch=1
	fi
done

echo "FATAL: could not push update files to $BRANCH after 5 attempts." >&2
exit 1
