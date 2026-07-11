# Follow-ups

Known limitations, deliberately not fixed yet (see PLAN.md scope rules):

- Markdown image syntax is dropped during chunking (chonkie's MarkdownChef extracts images
  separately); alt text is not indexed.
- Indexing two different root directories into the same store can collide: sources are stored as
  root-relative paths, so `a.md` under one root overwrites `a.md` under another. One store per
  notes collection is the assumption.
- `index --prune` only compares against the root being indexed; it cannot distinguish "file
  deleted" from "file lives under a different root" (same root cause as the collision above).

## Parking lot (deliberately not built yet)

- Chonkie's `CodeChunker`/`TableChunker` extras for structure-aware splitting of extracted code
  blocks and tables: the base install's character-based splitting is good enough until retrieval
  quality says otherwise.

## Rejected

- `--color auto|always|never`: the CLI emits no colored output (PLAN.md forbids a colors
  library), so the flag would be a knob that does nothing.
- Filtering/paging built into `query`: stdout is clean data; `grep`, `head`, and `jq` (with
  `--json`) already compose.
- Chonkie recipes (`from_recipe`): fetches chunking rules from Hugging Face Hub at runtime,
  which violates the no-network-at-runtime constraint. Rules are constructed locally instead.

## Resolved

- Stale chunks from edited files: re-indexing now deletes a source's chunks whose IDs are not in
  the new set; deleted files are handled by `index --prune`.
- `#` comments in fenced code blocks misread as headings: fixed by switching chunking to chonkie
  (MarkdownChef separates code from prose).
- Oversized single paragraphs never split: chonkie's RecursiveChunker splits them to size.
- cwd-relative data directories: everything now lives under `MICRORAG_HOME` (default
  `~/.microrag`).
- AGENTS.md placeholders and rules copied from another project: filled in / replaced.
- Shell tab completion: added via argcomplete.
- `microrag query -` (stdin): added.
