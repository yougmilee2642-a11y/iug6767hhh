#!/bin/bash
# macOS/Linux source-only archive builder. Never copies the live environment or business data.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT="$(dirname "$ROOT")"
STAMP="$(date +%Y%m%d-%H%M%S)"
TARGET="$PARENT/Callwise-local-source-$STAMP.zip"
[[ ! -e "$TARGET" ]] || { echo "Archive already exists: $TARGET" >&2; exit 1; }
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/callwise-archive.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$STAGE/Callwise"
while IFS= read -r -d '' file; do
  rel="${file#"$ROOT"/}"
  base="$(basename "$rel")"
  case "/$rel/" in
    */data/*|*/models/*|*/downloads/*|*/proof/*|*/outputs/*|*/work/*|*/.venv/*|*/venv/*|*/__pycache__/*|*/.pytest_cache/*|*/.git/*|*/node_modules/*|*/__MACOSX/*|*/secrets/*|*/.openai/*) continue ;;
  esac
  [[ "$rel" != "configs/integrations.local.json" ]] || continue
  case "$base" in
    .DS_Store|._*) continue ;;
    .env*)
      case "$base" in .env.example|.env.local.example) ;; *) continue ;; esac
      ;;
  esac
  case "${base##*.}" in pyc|zip|sqlite|sqlite3|db|log|key|pem|pfx|whl) continue ;; esac
  mkdir -p "$STAGE/Callwise/$(dirname "$rel")"
  cp -p "$file" "$STAGE/Callwise/$rel"
done < <(find "$ROOT" -type f -print0)

required=(
  '.env.local.example' 'requirements-local.txt' 'start-local.ps1' 'LOCAL_SETUP.md'
  'TEAM_DEVELOPMENT.md' 'providers/ollama.py' 'services/local_speech.py' 'scripts/smoke-local.py'
  'app.py' '.env.example' 'requirements.txt' 'README.md' 'requirement_contract.py'
  'evaluation/plan.py' 'evaluation/service.py' 'evaluation/knowledge.py' 'evaluation/preflight.py'
  'evaluation/provider_diagnostics.py' 'providers/errors.py' 'providers/capabilities.py'
  'static/evaluation.js' 'tests/test_iteration_3_2.py' 'build-archive.sh'
)
for entry in "${required[@]}"; do
  [[ -f "$STAGE/Callwise/$entry" ]] || { echo "Missing required source: $entry" >&2; exit 1; }
done

if find "$STAGE" \( -name '.DS_Store' -o -name '._*' -o -name '__MACOSX' -o -name '.env' -o -name '.env.*' \) \
  ! -name '.env.example' ! -name '.env.local.example' -print -quit | grep -q .; then
  echo 'Excluded file present in staging area.' >&2
  exit 1
fi

(cd "$STAGE" && zip -qr "$TARGET" Callwise)
unzip -t "$TARGET" >/dev/null
NAMES="$(unzip -Z1 "$TARGET")"
if printf '%s\n' "$NAMES" | grep -E '(^|/)(__MACOSX|\.DS_Store|\._[^/]+|\.venv|__pycache__|\.pytest_cache|node_modules)(/|$)' >/dev/null; then
  echo 'Archive contains macOS metadata or a cache path.' >&2
  rm -f "$TARGET"
  exit 1
fi
if printf '%s\n' "$NAMES" | grep -E '(^|/)\.env($|\.)' | grep -Ev '(^|/)\.env(\.local)?\.example$' >/dev/null; then
  echo 'Archive contains a non-example .env file.' >&2
  rm -f "$TARGET"
  exit 1
fi
printf 'Archive: %s\nEntries: %s\nSHA256: %s\n' \
  "$TARGET" "$(unzip -Z1 "$TARGET" | wc -l | tr -d ' ')" "$(shasum -a 256 "$TARGET" | awk '{print $1}')"
