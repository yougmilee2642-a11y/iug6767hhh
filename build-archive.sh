#!/bin/bash
# Archive committed sources only, without local data or submodule contents.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$(dirname "$ROOT")/focus-source-$(date +%Y%m%d-%H%M%S).zip"
[[ ! -e "$TARGET" ]] || { echo "Archive already exists: $TARGET" >&2; exit 1; }
git -C "$ROOT" archive --format=zip --prefix=focus/ --output="$TARGET" HEAD
printf 'Archive: %s\n' "$TARGET"
