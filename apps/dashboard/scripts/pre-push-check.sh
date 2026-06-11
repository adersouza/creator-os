#!/bin/bash
set -eo pipefail
echo "Pre-push checks..."

# Determine what's being pushed: only lint files in the commits being pushed,
# not every file that differs from origin/main.
# Read stdin for the ref range git provides to pre-push hooks.
LOCAL_SHA=""
REMOTE_SHA=""
while read -r _ local_sha _ remote_sha; do
  LOCAL_SHA="$local_sha"
  REMOTE_SHA="$remote_sha"
done

# If remote_sha is all zeros, this is a new branch — compare against origin/main
ZERO="0000000000000000000000000000000000000000"
if [ "$REMOTE_SHA" = "$ZERO" ]; then
  BASE="origin/main"
else
  BASE="$REMOTE_SHA"
fi

# 1. TypeScript type-check (catches type incompatibilities, schema drift)
echo "  [1/5] TypeScript..."
npx tsc --noEmit

# 2. Biome lint — only files in the commits being pushed
echo "  [2/5] Biome lint..."
CHANGED_FILES=$(git diff "$BASE".."$LOCAL_SHA" --name-only --diff-filter=d | grep -E '\.(ts|tsx|js|jsx)$' || true)
if [ -n "$CHANGED_FILES" ]; then
  # Filter to files that still exist (in case of renames/deletes)
  EXISTING_FILES=""
  for f in $CHANGED_FILES; do
    [ -f "$f" ] && EXISTING_FILES="$EXISTING_FILES $f"
  done
  if [ -n "$EXISTING_FILES" ]; then
    echo "$EXISTING_FILES" | xargs npx biome lint --diagnostic-level=error --no-errors-on-unmatched
  else
    echo "    No existing files to lint"
  fi
else
  echo "    No changed files to lint"
fi

# 3. Schema drift — block NEW (db as any).from() in pushed commits only
echo "  [3/5] Schema drift check..."
NEW_DRIFT=$(git diff "$BASE".."$LOCAL_SHA" -U0 -- 'api/**/*.ts' | grep '^\+' | grep -v '^+++' | grep "as any)\.from(" || true)
if [ -n "$NEW_DRIFT" ]; then
  echo "    BLOCKED: New (db as any).from() casts introduced:"
  echo "$NEW_DRIFT"
  echo "    Use typed queries or getSupabaseAny() for legitimate cases."
  exit 1
fi

# 4. New AI calls without aiCache?
echo "  [4/5] AI cache check..."
NEW_AI=$(git diff "$BASE".."$LOCAL_SHA" --name-only --diff-filter=A | grep -E "api/ai/" || true)
if [ -n "$NEW_AI" ]; then
  for f in $NEW_AI; do
    if ! grep -q "aiCache\|getCached" "$f" 2>/dev/null; then
      echo "    WARNING: $f — no aiCache usage found"
    fi
  done
fi

# 5. New API endpoints without withAuth? New crons without withCronLock?
echo "  [5/5] Auth/cron guard check..."
NEW_API=$(git diff "$BASE".."$LOCAL_SHA" --name-only --diff-filter=A | grep -E "^api/" | grep -v "_lib\|cron" || true)
if [ -n "$NEW_API" ]; then
  for f in $NEW_API; do
    if ! grep -q "withAuth\|withCron\|verifyCronAuth" "$f" 2>/dev/null; then
      echo "    WARNING: $f — no withAuth/withCron found"
    fi
  done
fi
NEW_CRON=$(git diff "$BASE".."$LOCAL_SHA" --name-only --diff-filter=A | grep "api/cron/" || true)
if [ -n "$NEW_CRON" ]; then
  for f in $NEW_CRON; do
    if ! grep -q "withCronLock\|withCron" "$f" 2>/dev/null; then
      echo "    WARNING: $f — no withCronLock found"
    fi
  done
fi

echo "Pre-push checks complete"
