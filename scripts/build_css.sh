#!/usr/bin/env bash
# Build arciv_api/static/app.css from styles/input.css with the standalone
# Tailwind v4 CLI plus the vendored DaisyUI plugin. No npm project required.
#
# The Tailwind binary is downloaded once to .tooling/ (gitignored). The DaisyUI
# plugin files (styles/daisyui*.js) and the built app.css are committed so the
# app runs without this step; re-run it after changing templates or styles.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TW_VERSION="v4.3.1"
TW="$ROOT/.tooling/tailwindcss"

if [[ ! -x "$TW" ]]; then
  mkdir -p "$ROOT/.tooling"
  echo "Downloading Tailwind standalone CLI $TW_VERSION…"
  curl -sL --fail -o "$TW" \
    "https://github.com/tailwindlabs/tailwindcss/releases/download/$TW_VERSION/tailwindcss-linux-x64"
  chmod +x "$TW"
fi

echo "Building CSS…"
"$TW" \
  -i "$ROOT/arciv_api/styles/input.css" \
  -o "$ROOT/arciv_api/static/app.css" \
  --minify

echo "Wrote arciv_api/static/app.css ($(wc -c < "$ROOT/arciv_api/static/app.css") bytes)"
