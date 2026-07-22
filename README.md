# Arciv

[![CI](https://github.com/MichaelVerdegaal/Arciv/actions/workflows/ci.yml/badge.svg)](https://github.com/MichaelVerdegaal/Arciv/actions/workflows/ci.yml)

Arciv is a CLI tool that allows you to build your personal archive of reading material as clean
markdown.

Fetch research papers, blog posts and other web content, and store them in a local SQLite database.

## What It Does

Three stages, no writeback into your notes:

1. Indexing: extract links from your files; every link is recorded with the file it came from and
   when it was indexed
2. Fetching: download raw pages (browser for HTML, direct HTTP for PDFs)
3. Parsing: validate and convert to markdown, archived on disk with SQLite tracking state

The stored markdown is plain prose: bold/italic/inline-code markers are stripped (the text is kept)
so the archive reads uniformly. The raw HTML stays on disk next to the markdown, so the original
formatting is never lost (`arciv parse --reparse` re-converts from disk).

## Usage

Archive things directly, a single URL, a single file, or a whole directory:

```bash
arciv get https://example.com/post   # archive one URL
arciv get --file note.md             # archive all links in one file
arciv get --dir path/to/notes        # archive all links in a directory
```

Sometimes the note is boring but its links aren't. `extract` prints the URLs found in a note
(one per line, deduplicated) without archiving anything — no database writes, no fetching — so
links can be inspected, filtered, and piped onward:

```bash
arciv extract note.md                # print the URLs in a note
arciv extract a.md b.md              # extract from many notes, deduped across them
arciv extract note.md | arciv get -  # archive a note's links, not the note
cat note.md | arciv extract -        # read note text from stdin
```

Feed note *paths* (not text) with `-f/--files-from`; each line is a note file to read, and `-` reads
the paths from stdin, so `extract` chains after any command that lists notes:

```bash
arciv extract -f notes.txt                  # extract from every note listed in notes.txt
arciv search query ... | arciv extract -f - # extract from note paths piped in
arciv extract a.md -f -                     # a.md plus every note path from stdin
```

Unreadable files are logged to stderr and skipped; the run still prints the URLs it could gather.

The same idea works for webpages that are pure link hubs (a web book's ToC, a link roundup):
`get --no-save` fetches the page, prints its links (absolute, deduplicated) to stdout, and archives
nothing — no database row, no saved files:

```bash
arciv get https://book.example/toc --no-save               # print the page's links
arciv get https://book.example/toc --no-save | arciv get -  # archive them all
```

The printed links are raw: filtering belongs to grep in the middle of the pipe, and the downstream
`get -` applies the URL rules anyway.

Register directories you index repeatedly as named sources:

```bash
arciv source add ~/vault/daily-notes notes  # register a source and archive it
arciv source add ~/vault/notes notes --no-archive  # register only, archive later
arciv source update notes            # re-index, fetch, and parse one source
arciv source update --all            # update every registered source
arciv source                         # list registered sources
arciv source remove notes            # unregister it (asks first)
arciv source remove notes --remove-files  # also delete files only it links
```

`source add` and `source update` run the whole pipeline (index, then a single batched fetch, then
parse) so a source goes from registered to archived in one command. The individual `index`, `fetch`,
and `parse` stages stay available for development. The difference from `get`: `get` is a one-shot
archive that tracks nothing, while a source is registered and re-syncable with `source update`.

Run individual pipeline stages:

```bash
arciv fetch                          # download indexed URLs still pending
arciv fetch --refetch                # re-download every known page
arciv parse                          # convert fetched pages to markdown
arciv parse --reparse                # re-parse everything from disk
```

Inspect the archive:

```bash
arciv status                         # pipeline counts + failure summary
arciv list -n 50                     # fetched pages: time, domain, URL
arciv list --domain medium.com       # only pages from one domain
arciv list --source notes            # only pages indexed from one source
arciv path https://example.com/post  # filepath of its archived markdown
arciv prune failed                   # drop stale rows: missing | failed | all
arciv db dir                         # where the archive lives on disk
arciv db remove                      # delete the database (asks first)
```

URL rules skip or rewrite URLs before they are fetched. They are data, not commands: the packaged
defaults handle medium, github, huggingface, and a set of policy skips (youtube, sharepoint, and so
on). To add your own, create a `rules.toml` in the data dir (see `arciv db dir`); user rules load
ahead of the defaults, so they win on first match.

```bash
arciv rules list                              # active rules, in the order they apply
arciv rules test https://medium.com/@me/post  # show how the rules treat a URL
```

A rule is a match (`domain`, `host`, `starts_with`, or `regex`) plus an ordered list of actions
(`skip`, `prepend`, `replace`, `regex_replace`). Rewrite rules should be idempotent. Processing runs
again at fetch time, so an action whose output its own match would rewrite differently (e.g. a
`prepend` the match still fires on) would stack. The shipped defaults are idempotent; keep yours
that way too:

```toml
[[rule]]
name = "arxiv abstract to pdf"
type = "regex"
match = '^https://arxiv\.org/abs/'
  [[rule.action]]
  type = "regex_replace"
  pattern = '^https://arxiv\.org/abs/(.*)$'
  replacement = "https://arxiv.org/pdf/$1"
```

`rules test` runs a URL through the same processing the index and fetch stages use (the in-code
plumbing guards, then the rules, then canonicalization) and prints the verdict: `skipped` (with the
reason), `rewritten` (with the target), or `passthrough`, naming the rule that fired so you can tune
a rule and check it without a full index run.

### Global options and pipes

Data goes to stdout; all logs and diagnostics go to stderr, so `arciv list | cat` shows only data.
Global flags work before or after the command:

```bash
arciv -v fetch         # more detail (-v debug, -vv trace)
arciv fetch -v         # same thing
arciv -q fetch         # errors only
arciv --color never list
arciv --json status    # machine-readable output on stdout
arciv --version        # print the installed version and exit
```

With `--json`, `status` and `path` emit one JSON object, while `list`, `source`, and `rules list`
emit JSONL (one object per line) so they stream into `head`/`grep`/`jq`. The mutating commands
(`source update`, `get`, `fetch`, `parse`) emit a single `{indexed, fetched, parsed, failed}`
summary, so a script can assert the outcome without a follow-up `status --json`. The commands
compose with standard Unix tools:

```bash
# Re-archive every page from a given domain found in the archive
arciv list --json | jq -r .url | grep medium.com | arciv get -

# NUL-separated output survives odd characters and feeds xargs -0
arciv list -n 0 --null | xargs -0 -n1 echo
```

`arciv get -` reads newline-separated URLs from stdin.

## Search

Semantic search over your markdown is an optional extra, so a plain `arciv` install stays light.
Install it with the `search` extra:

```bash
uv tool install "arciv[search]"
arciv search download                 # one-time embedding-model fetch (the only networked step)
arciv search index ~/vault/notes      # chunk + embed every *.md under a directory
arciv search query "onnx throughput"  # top matches across everything indexed
```

`arciv search query` prints one absolute file path per line, best match first, so it pipes straight
into the archiver: search your notes, then archive the links in the notes that matched.

```bash
arciv search query "vector databases" | arciv extract -f - | arciv get -
```

`arciv search refresh` re-indexes each collection from the root it was built from, `arciv search
status` shows where the model and index live plus per-collection counts, and `arciv search
collections` lists them. `arciv search <command> --help` is the per-command reference. Without the
extra installed, `arciv search` just prints an install hint.

The vector index (a local Chroma store) and the model live under the Arciv data dir by default
(`arciv search status` prints the paths); an existing `~/.microrag` from the standalone MicroRag
tool is reused as-is. The index is derived data: delete it and rebuild from your notes any time.

See [SETUP.md](SETUP.md) for installation and configuration.

## The Name

"Arciv" is a compact respelling of *archivum*, the Latin root of "archive".