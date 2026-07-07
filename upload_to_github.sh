#!/usr/bin/env bash

set -euo pipefail

TARGET_REPO_URL="https://github.com/Dennis-Spera/mongodb-json-generator.git"
DEFAULT_REMOTE="origin"

usage() {
  cat <<'EOF'
Usage:
  ./upload_to_github.sh "commit message" [branch] [remote]

Examples:
  ./upload_to_github.sh "Update generator UX"
  ./upload_to_github.sh "Fix cancel button" master
  ./upload_to_github.sh "Release changes" main upstream

Behavior:
  - Adds all changes
  - Commits with the provided message
  - Pushes to the selected remote and branch
  - If the remote does not exist, it is created and pointed to:
    https://github.com/Dennis-Spera/mongodb-json-generator.git
EOF
}

if ! command -v git >/dev/null 2>&1; then
  echo "Error: git is not installed or not in PATH."
  exit 1
fi

if [ "$#" -lt 1 ]; then
  usage
  exit 1
fi

COMMIT_MESSAGE="$1"
BRANCH="${2:-$(git branch --show-current || true)}"
REMOTE="${3:-$DEFAULT_REMOTE}"

if [ -z "$BRANCH" ]; then
  echo "Error: could not determine current branch. Pass branch as second argument."
  exit 1
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Error: this script must be run inside a git repository."
  exit 1
fi

if git diff --quiet && git diff --cached --quiet; then
  echo "No changes detected. Nothing to commit."
  exit 0
fi

if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
  echo "Remote '$REMOTE' not found. Adding it as: $TARGET_REPO_URL"
  git remote add "$REMOTE" "$TARGET_REPO_URL"
else
  CURRENT_URL="$(git remote get-url "$REMOTE")"
  if [ "$CURRENT_URL" != "$TARGET_REPO_URL" ]; then
    echo "Warning: remote '$REMOTE' points to: $CURRENT_URL"
    echo "Expected: $TARGET_REPO_URL"
    echo "Continuing with existing remote URL."
  fi
fi

echo "Staging changes..."
git add -A

# Safety net: unstage known temporary/editor artifacts.
git reset -q HEAD -- '*.tmp' '*.tmp.*' '*.swp' '*~' || true

echo "Creating commit..."
git commit -m "$COMMIT_MESSAGE"

echo "Pushing to $REMOTE/$BRANCH..."
git push -u "$REMOTE" "$BRANCH"

echo "Done. Changes uploaded."