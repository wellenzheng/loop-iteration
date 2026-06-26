#!/usr/bin/env bash
# Publish the public release to GitHub.
#
# Workflow: develop on `main` (full internal history) -> run this to sync the
# `public` branch (internal-only paths stripped) and push it to github/main.
#
# Internal-only paths listed below are removed from the public branch on every
# sync, so merging `main` never leaks them.
set -euo pipefail

REMOTE="github"
LOCAL_BRANCH="public"
REMOTE_BRANCH="main"

# Paths that exist on `main` but must NOT appear in the public release.
INTERNAL_PATHS=(
  "docs/superpowers"   # internal design specs + plans
  "docs/report.md"     # internal milestone report
)

echo "==> updating $LOCAL_BRANCH from main"
git checkout "$LOCAL_BRANCH"
git merge main --no-edit

echo "==> stripping internal-only paths"
stripped=0
for p in "${INTERNAL_PATHS[@]}"; do
  if git ls-files --error-unmatch "$p" >/dev/null 2>&1; then
    git rm -r --quiet "$p"
    stripped=1
    echo "    removed $p"
  fi
done
if [ "$stripped" = 1 ]; then
  git commit -q -m "chore(public): strip internal-only paths from release"
fi

echo "==> pushing $LOCAL_BRANCH -> $REMOTE/$REMOTE_BRANCH"
git push "$REMOTE" "$LOCAL_BRANCH:$REMOTE_BRANCH"

echo "==> done"
git checkout main
