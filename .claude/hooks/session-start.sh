#!/bin/bash
# SessionStart hook for Claude Code on the web: make a fresh sandbox ready
# for Arciv development in one shot.
#
# - Installs the locked dependencies with uv (same as CI).
# - Puts the venv on PATH so pytest/ruff/mypy/arciv resolve directly.
# - Points ARCIV_DATA_DIR at a disposable temp dir so ad-hoc CLI runs never
#   write an archive into the container's home directory.
# - Bridges the image's pre-installed Chromium into the layout patchright
#   expects, because the browser CDN is blocked by the sandbox egress proxy
#   (`scrapling install` cannot work there). See .claude/skills/verify for
#   how to use the browser to verify fetch changes end to end.
set -euo pipefail

# Local sessions already have an environment; this setup is sandbox-only.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

uv sync --frozen

{
  echo "export PATH=\"$CLAUDE_PROJECT_DIR/.venv/bin:\$PATH\""
  echo 'export ARCIV_DATA_DIR="${ARCIV_DATA_DIR:-/tmp/arciv-data}"'
} >> "$CLAUDE_ENV_FILE"

# --- Browser bridge (best effort: everything except live fetching works
# without it, so a layout change in the base image must not fail the hook) ---
bridge_browser() {
  local browsers_json revision bridge src inner
  browsers_json=$(echo .venv/lib/python3.*/site-packages/patchright/driver/package/browsers.json)
  [ -f "$browsers_json" ] || { echo "patchright not installed; skipping browser bridge"; return; }
  [ -d /opt/pw-browsers ] || { echo "/opt/pw-browsers missing; skipping browser bridge"; return; }

  revision=$(.venv/bin/python -c "
import json, sys
data = json.load(open(sys.argv[1]))
print(next(b['revision'] for b in data['browsers'] if b['name'] == 'chromium'))
" "$browsers_json")

  # Exact revision already present: use the image's browsers dir as-is.
  if [ -d "/opt/pw-browsers/chromium-$revision" ]; then
    echo 'export PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers' >> "$CLAUDE_ENV_FILE"
    echo "browser: chromium-$revision found in /opt/pw-browsers"
    return
  fi

  # Otherwise symlink whatever Chromium the image ships under the pinned
  # revision. Handles both directory layouts (chrome-linux and chrome-linux64).
  src=$(echo /opt/pw-browsers/chromium-[0-9]*)
  [ -d "$src" ] || { echo "no Chromium under /opt/pw-browsers; skipping browser bridge"; return; }
  inner=$(echo "$src"/chrome-linux*)
  [ -d "$inner" ] || { echo "unexpected layout in $src; skipping browser bridge"; return; }

  bridge=/tmp/pw-bridge
  mkdir -p "$bridge/chromium-$revision" "$bridge/chromium_headless_shell-$revision"
  ln -sfn "$inner" "$bridge/chromium-$revision/chrome-linux64"
  touch "$bridge/chromium-$revision"/{INSTALLATION_COMPLETE,DEPENDENCIES_VALIDATED}
  local shell_src shell_inner
  shell_src=$(echo /opt/pw-browsers/chromium_headless_shell-[0-9]*)
  if [ -d "$shell_src" ]; then
    shell_inner=$(echo "$shell_src"/chrome-linux*)
    ln -sfn "$shell_inner" "$bridge/chromium_headless_shell-$revision/chrome-linux64"
    touch "$bridge/chromium_headless_shell-$revision"/{INSTALLATION_COMPLETE,DEPENDENCIES_VALIDATED}
  fi
  echo "export PLAYWRIGHT_BROWSERS_PATH=$bridge" >> "$CLAUDE_ENV_FILE"
  echo "browser: bridged $src -> $bridge/chromium-$revision"
}
bridge_browser || echo "browser bridge failed; fetch verification needs manual setup (see .claude/skills/verify)"

echo "arciv sandbox ready: deps synced, venv on PATH, ARCIV_DATA_DIR defaults to /tmp/arciv-data"
