---
name: verify
description: How to run Arciv's fetch pipeline for real in a sandboxed session (local HTTPS site, pre-installed Chromium) to verify fetch/crawl/parse changes end to end.
---

# Verifying Arciv end to end

Unit tests fake the browser; real verification means running `arciv get` against a live
server. In a Claude Code web session the open internet is blocked by the egress proxy, so
use a local HTTPS site.

## Browser (web sessions only)

The SessionStart hook (`.claude/hooks/session-start.sh`) normally does this already:
`PLAYWRIGHT_BROWSERS_PATH` is exported for the session and the browser just works. If the
hook didn't run (or the bridge failed), do it manually — `scrapling install` fails (browser
CDN blocked), so bridge the pre-installed Chromium instead. Patchright expects the
`chrome-linux64/` layout under its pinned revision (check `browsers.json` in the patchright
package for the number, 1223 below):

```bash
mkdir -p /tmp/pw/chromium-1223 /tmp/pw/chromium_headless_shell-1223
ln -s /opt/pw-browsers/chromium-*/chrome-linux /tmp/pw/chromium-1223/chrome-linux64
ln -s /opt/pw-browsers/chromium_headless_shell-*/chrome-linux /tmp/pw/chromium_headless_shell-1223/chrome-linux64
touch /tmp/pw/chromium-1223/{INSTALLATION_COMPLETE,DEPENDENCIES_VALIDATED}
touch /tmp/pw/chromium_headless_shell-1223/{INSTALLATION_COMPLETE,DEPENDENCIES_VALIDATED}
export PLAYWRIGHT_BROWSERS_PATH=/tmp/pw
```

## Local HTTPS site

The plumbing guards skip non-HTTPS, localhost, and IP hosts, so the site needs a hostname
alias and TLS. The stealth session sets `ignore_https_errors`, so a self-signed cert works:

```bash
echo "127.0.0.1 book.test" >> /etc/hosts
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 7 -nodes \
  -subj "/CN=book.test" -addext "subjectAltName=DNS:book.test"
# python3: http.server.HTTPServer on :443 wrapped in ssl.SSLContext with that cert,
# serving .html files that link to each other (relative + absolute hrefs both resolve)
export no_proxy="$no_proxy,book.test" NO_PROXY="$NO_PROXY,book.test"  # bypass egress proxy
```

## Drive it

```bash
export ARCIV_DATA_DIR=/tmp/arciv-data   # keep the archive out of the real data dir
arciv get https://book.test/toc.html --depth 2
arciv status && arciv list
```

Pages need ~50+ words of plain prose or the parse stage rejects them; trafilatura still
rejects some minimal link-only pages with "extraction failed" — that's the parse floor,
not a fetch bug. Rerunning the same command verifies resume (0 new fetches, links still
walked from the HTML on disk).
