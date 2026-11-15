#!/usr/bin/env bash
# Upload the compact archive to GitHub Releases.
# Requires the GitHub CLI (gh) and an authenticated account: gh auth login
set -euo pipefail

TAG="${1:-v2.0.0}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="$ROOT/falconia-compact.sqlite"
ZST="$ROOT/falconia-compact.sqlite.zst"
SUM="$ROOT/falconia-compact.sqlite.sha256"

for f in "$DB" "$ZST"; do
  [ -f "$f" ] || { echo "Missing $f. Build it with: python Falconia_Data.py ingest Falconia_Excerpt.csv --db falconia-compact.sqlite --compact" >&2; exit 1; }
done
( cd "$ROOT" && sha256sum falconia-compact.sqlite > falconia-compact.sqlite.sha256 )

ASSETS=("$DB" "$ZST")
[ -f "$SUM" ] && ASSETS+=("$SUM")

gh release create "$TAG" "${ASSETS[@]}" \
  --title "Falconia compact archive $TAG" \
  --notes "13.676.796 rows. Download falconia-compact.sqlite.zst, run: zstd -d falconia-compact.sqlite.zst, then python Falconia_Data.py serve --db falconia-compact.sqlite"
