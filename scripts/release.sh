#!/usr/bin/env bash
set -euo pipefail

BUMP_TYPE=${1:-patch}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

# --- Read current version ---
CURRENT=$(python3 -c "
import re
with open('pyproject.toml') as f:
    m = re.search(r'version = \"(.+?)\"', f.read())
    print(m.group(1))
")

IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"

case "$BUMP_TYPE" in
  patch) PATCH=$((PATCH + 1)) ;;
  minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
  major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
  *) echo "Usage: $0 [patch|minor|major]"; exit 1 ;;
esac

NEW_VERSION="${MAJOR}.${MINOR}.${PATCH}"
echo ">> Bumping $CURRENT → $NEW_VERSION ($BUMP_TYPE)"

# --- Bump pyproject.toml ---
python3 -c "
import re, sys
current, new = sys.argv[1], sys.argv[2]
with open('pyproject.toml') as f:
    content = f.read()
content = re.sub(
    r'(version = \")' + re.escape(current) + r'(\")',
    r'\g<1>' + new + r'\g<2>',
    content, count=1
)
with open('pyproject.toml', 'w') as f:
    f.write(content)
" "$CURRENT" "$NEW_VERSION"

# --- Generate changelog entries ---
LAST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || true)
if [ -n "$LAST_TAG" ]; then
    GIT_LOG=$(git log "${LAST_TAG}..HEAD" --pretty=format:"- %s" --no-merges 2>/dev/null || true)
else
    GIT_LOG=$(git log --pretty=format:"- %s" --no-merges | head -20 || true)
fi
[ -z "$GIT_LOG" ] && GIT_LOG="- maintenance and improvements"

DATE=$(date +%Y-%m-%d)

python3 -c "
import sys
version, date, entries = sys.argv[1], sys.argv[2], sys.argv[3]
new_section = '## [' + version + '] - ' + date + '\n\n' + entries + '\n'

try:
    with open('CHANGELOG.md') as f:
        existing = f.read()
    lines = existing.split('\n')
    insert_at = len(lines)
    for i, line in enumerate(lines):
        if i > 0 and line.startswith('## '):
            insert_at = i
            break
    lines.insert(insert_at, new_section)
    content = '\n'.join(lines)
except FileNotFoundError:
    content = '# Changelog\n\n' + new_section

with open('CHANGELOG.md', 'w') as f:
    f.write(content)
print('>> CHANGELOG.md updated')
" "$NEW_VERSION" "$DATE" "$GIT_LOG"

# --- Commit + tag ---
git add pyproject.toml CHANGELOG.md
git commit -m "chore: release v${NEW_VERSION}"
git tag -a "v${NEW_VERSION}" -m "Release v${NEW_VERSION}"

echo ""
echo ">> Released v${NEW_VERSION}"
echo "   Tag: v${NEW_VERSION}"
echo "   Run 'make redeploy' to deploy (or 'make release-*' already does it)"
