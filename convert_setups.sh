#!/bin/sh
# Usage: sh convert_setups.sh inventory_setups.json
# Writes next to the input file:
#   converted_<name>.md   bank tag import strings, one section per setup
#   setups.html           lazy-loading viewer (search, icons, copy buttons)
#   icons/                item icons, downloaded once and reused on later runs
# Keep this script in the same folder as build_viewer.py.
# Optional: SETUPS_UA="my-tool - @yourname" sh convert_setups.sh file.json

command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 1; }
here=$(cd "$(dirname -- "$0")" && pwd)
[ -f "$here/build_viewer.py" ] || { echo "build_viewer.py must sit next to this script" >&2; exit 1; }
[ $# -gt 0 ] || { echo "Usage: $0 file.json" >&2; exit 1; }

for f in "$@"; do
  [ -f "$f" ] || { echo "Skipping (not a file): $f" >&2; continue; }
  dir=$(dirname -- "$f")
  base=$(basename -- "$f" .json)
  python3 "$here/build_viewer.py" "$f" -o "$dir" --html-name setups.html \
    --md "$dir/converted_$base.md" \
    --ua "${SETUPS_UA:-osrs-setup-viewer (personal tool)}" || echo "Failed: $f" >&2
done
