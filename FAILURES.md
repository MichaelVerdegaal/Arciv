# Failure Audit

Snapshot of `data/clotho.db` and `execution.log`. The run did not complete: 1098 URLs total, 326
fetched, **55 failed**, 717 still pending.

## Failure categories

| Category | Count | Root cause | Fixable? |
|---|---|---|---|
| too short (`<150` words) | 39 | Mostly genuine: landing pages, JS-rendered SPAs, login walls. A minority are false negatives from code stripping. | Partly |
| extraction failed | 7 | trafilatura returns `None` — dynamic app shells (Power BI, Copilot Studio, LinkedIn), auth walls. | Mostly no |
| html suspiciously small | 3 | Redirect stubs / non-HTML download endpoints. | No |
| PDF download failed | 2 | One expired pre-signed S3 URL (SSRN), one slow preprint host. | 1 of 2 |
| block page | 2 | ResearchGate Cloudflare challenge. | No |
| DNS resolution failed | 1 | `mlops-tools.com` no longer resolves (dead domain). | No |
| PDF parse error | 1 | HuggingFace `/blob/` URL returns HTML, not the PDF. | Yes (URL rewrite) |

## False-negative audit of "too short"

The word-count gate (`< 150`) runs **after** markdown extraction. Extraction currently uses
`favor_precision=True` and `strip_code=True` (prunes every `<pre>`/`<code>` element). I re-fetched a
representative sample and re-extracted under four settings to check whether real content was being
dropped:

| URL | current (strip_code) | keep code + precision | keep code + recall | verdict |
|---|---|---|---|---|
| tsfresh.readthedocs.io | **161** | 161 | 161 | now passes (networkidle fix) |
| github.com/apple/ml-sigma-reparam | 118 ❌ | **166** | 166 | **false negative** (code stripped) |
| github.com/doobidoo/mcp-memory-service | 38 ❌ | 38 | 103 | borderline — mostly code |
| dspy.ai | 146 ❌ | 146 | 146 | genuine near-miss (JS tabs) |
| onnx.ai/get-started | 93 ❌ | 93 | 122 | genuine — short landing |
| docs.goauthentik.io | 105 ❌ | 105 | 108 | genuine — short stub |
| learn.microsoft.com/.../ai-studio | 80 ❌ | 80 | 44 | genuine — JS app shell |
| supermaven.com/about | 83 ❌ | 83 | 135 | genuine — marketing page |
| kaggle.com/code/... | 30 ❌ | 32 | 55 | genuine — login wall |
| matrixprofile.org | 65 ❌ | 0 | 32 | genuine — JS SPA |
| neuralprophet.com | 28 ❌ | 23 | 45 | genuine — 6 KB landing |

**Conclusion:** the large majority of "too short" rejections are correct — they are genuinely thin
pages (marketing, login walls, JS SPAs that need real rendering). The one reproducible
false-negative pattern is **code-heavy GitHub README / docs pages**, where `strip_code=True` removes
the `<pre>`/`<code>` content *before* the length gate, so a page with real prose plus a lot of code
is rejected as too short (e.g. ml-sigma-reparam: 118 → 166 with code kept).

No content was silently lost: failed pages are not archived, so nothing was overwritten or deleted —
they simply were not stored.

## Fixes

### Applied
- Image/stylesheet/font request blocking, `networkidle` wait, headless mode, `ignore_https_errors`
  (earlier phase). These already recovered borderline pages such as tsfresh (141 → 161).

### Proposed — needs confirmation (pipeline / rewriter changes per AGENTS.md)
1. **Length gate vs. code stripping.** Apply the `< 150` word gate to the *full* extraction (code
   included) while continuing to store the code-stripped markdown. Removes the only systematic
   false-negative without polluting stored content with code.
2. **HuggingFace `/blob/` PDFs.** Rewrite `huggingface.co/<repo>/blob/<rev>/<file>.pdf` →
   `.../resolve/<rev>/<file>.pdf` so the real PDF is downloaded.

### Won't fix (out of scope / not recoverable)
- Cloudflare challenge pages (ResearchGate), dynamic app shells (Power BI, Copilot Studio,
  LinkedIn), dead domains (DNS), expired pre-signed PDF URLs.
