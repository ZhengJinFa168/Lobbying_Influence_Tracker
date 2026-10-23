# CLAUDE.md

Lobby Echo: a Python 3.12 pipeline that traces Have Your Say comments on the EU AI Act into amendments and the final law.
Neo4j 5 (APOC + GDS, via Docker) is the single source of truth; Python does embeddings, similarity and LLM judging and writes results back.
Read `README.md` for the findings and `docs/ARCHITECTURE.md` / `docs/IMPLEMENTATION_PLAN.md` for design. This file is about *how to work here*.

## Stack and layout

| Area | What lives there |
|---|---|
| `pipeline/` | Stages `sNN_*.py` (S00-S12), each exposing `main(track)`; shared `config.py`, `graph.py` (Neo4j), `llm.py` (OpenRouter client + sqlite cache), `embed.py`, `sources.py`, `textutil.py`, `units.py`, `serve.py` (local proxy), HTML templates |
| `neo4j/` | `docker-compose.yml`, `schema.cypher`, `queries/01-13_*.cypher` (run by S10), `demo/demo_queries.cypher` |
| `WebScraping/`, `amendments/` | Have Your Say scraper/parser; ParlTrack dumps (`*.zst`, not in git) and the legacy amendments dashboard |
| `data_sources/` | `sources.yaml`, EUR-Lex raw HTML + parsed units, LobbyFacts / Integrity Watch CSVs |
| `demo/` | Prebuilt `demo.html`, `dashboard.html`, `REVERSA_PPT.html` (committed outputs of S11/S11b) |
| `data/` | Generated caches, features, `llm_cache.sqlite`, `llm_costs.csv`, results. Gitignored |

Commands:

```bash
.venv/bin/python -m pipeline.run                 # all stages, both tracks
.venv/bin/python -m pipeline.run --only s00      # sanity check (sources, Neo4j, plugins, schema)
.venv/bin/python -m pipeline.run --from s07 --track B
docker compose -f neo4j/docker-compose.yml --env-file .env up -d
```

```bash
.venv/bin/tach check                             # module boundaries (also run by pre-commit and CI)
uv pip install --python .venv/bin/python -r requirements-dev.txt && .venv/bin/pre-commit install   # once per clone
```

There is no test suite; S00 (`s00_check`) and S12 (`s12_eval`) are the checks. After changing a stage, run it with `--only sNN`, then S00, then `tach check`.

## Contracts and boundaries

Humans own interfaces and contracts; agents own module internals.

- **Protected files: never edit without asking the user first.** A `PreToolUse` hook (`.claude/hooks/guard_protected.py`) sends every write to these for approval,
  and `.github/CODEOWNERS` requires the owner's review on PRs. Do not work around either one (no Bash writes, no copies, no disabling the hook).
  - Graph contract: `neo4j/schema.cypher`, `docs/IMPLEMENTATION_PLAN.md`, `docs/neo4j_graph_schema.md`
  - Procedure config: `data_sources/procedures/*.yaml` (one file per law; the format is fixed, fill `TODO` values only with approval)
  - Linter config: `tach.toml`, `.pre-commit-config.yaml`, `requirements-dev.txt`
  - Tests: `tests/`, `test_*.py`, `*_test.py`, `conftest.py`
  - CI: `.github/`
  - Guardrails: `CLAUDE.md`, `.claude/settings.json`, `.claude/settings.local.json`, `.claude/hooks/`, `.claude/agents/`
- **Modules talk only through their public entry points**, as declared in `tach.toml`:
  - A stage's only public name is `main(track)`; `pipeline/run.py` calls it. Stages do not import from other stages.
  - The shared core (`config`, `graph`, `llm`, `embed`, `sources`, `textutil`, `units`) may be imported by anyone, public (non-underscore) names only,
    and never imports a stage.
  - Code two stages need goes into a shared module (a hotspot file: small, separate commit), not into a cross-stage import.
    Stages exchange data through Neo4j and the paths in `config.py`, not through Python objects.
  - Never make `tach check` pass by adding `depends_on` or `expose` entries (or by running `tach sync`); that is a change to `tach.toml` and needs the user's approval.
  - A new file under `pipeline/` is unusable until it is declared in `tach.toml`: ask the user to add it.
  - Tach checks `from X import name`, not attribute access on a module (`graph._x`). Do not use underscore names from another module either way.
- Known violations from before the boundaries existed are listed in `TASKS.md` → *Boundary debt*. `tach check` fails until they are fixed.

## Orchestration: Claude leads, Gemini reads and reviews

Claude (this session) is the orchestrator: it plans, decides, edits code and talks to the user.
Gemini runs through the Antigravity CLI `agy` in headless print mode as a cheap second pair of eyes. Use it for:

1. **Heavy research / reading**: questions that need many files read (for example "which stages write `ECHOED_IN` and with which properties?",
   "trace how `carrier_met` is computed from S06b to S10", "summarise every Cypher query in `neo4j/queries/`").
   Delegate to the `gemini-researcher` agent instead of reading a dozen files into the main context.
2. **Independent code review**: run the `gemini-reviewer` agent on **every diff before committing**, and on the branch diff before opening a PR.
   Treat its findings as leads to verify, not as truth; fix confirmed ones or tell the user why not.

Do the work yourself (no Gemini) for single-file reads, small edits, and anything that needs a decision from the user.

### How to call `agy`

```bash
agy -p "<prompt>" --mode plan --model gemini-3.8-flash-medium --print-timeout 300s
```

- `-p` runs one prompt non-interactively. `agy` runs in the current directory and **can read repo files itself**: name the paths in the prompt.
- **`agy -p` does not read stdin.** `git diff | agy -p "..."` sends nothing. Put content in the prompt argument instead:
  `agy -p "$(printf 'Review this diff:\n\n'; git diff)"`.
- `--mode plan` keeps Gemini read-only. Never pass `--dangerously-skip-permissions`; headless `agy` cannot run shell commands without it, which is what we want.
  Tell Gemini in the prompt to use only its file-reading tool, or it may try `grep`/`cat`, get denied, and return nothing.
- **`agy` exits 0 even when it did nothing.** An output starting `jetski: no output produced` means a tool was denied; retry with a stricter prompt.
- Models: `gemini-3.8-flash-medium` for search and summaries, `gemini-4-argon-high` for reviews and tricky reasoning (`agy models` lists all).
- Always set `--print-timeout`; a hung call should fail, not block the session.
- Ask for a structured answer (file:line references, bullet findings) so the result is easy to verify.

### What never goes to Gemini

`agy` sends prompts and the files it reads to Google. Never put in a prompt, or ask it to read:
`.env` (Neo4j password, `OPENROUTER_API_KEY`), anything under `~/.gemini`, or credentials of any kind.
Scraped consultation data and code are fine.

### Verifying Gemini's output

Gemini can be wrong or invent file names. Before acting on a finding, open the cited file/line yourself.
Report to the user what Gemini said *and* whether you confirmed it.

## Multi-developer safety

Several people work on this repo (see `git shortlog -sn`) on branches such as `main`, `pipeline-implementation`, `stepbystep-implementation`.

- **Claim before you edit.** Check `TASKS.md` before starting. Add or update your row (owner, module, branch) and commit that first, so others see it.
  Do not edit files in a module someone else has claimed as *In progress*; coordinate first.
- **Branches, not `main`.** Work on a feature branch; open a PR to `main`. Never force-push a shared branch, never rewrite pushed history.
- **Pull before you start, and before you push.** `git pull --rebase` on your branch; resolve conflicts, do not discard others' changes.
- **Shared-hotspot files** touched by everyone: `pipeline/config.py`, `pipeline/graph.py`, `pipeline/llm.py`, `pipeline/run.py` (`STAGES`), `neo4j/schema.cypher`,
  `requirements.txt`. Keep changes there small, in their own commit, and mention them in the PR description.
- **Graph contract.** Node labels, relationship types and properties are a contract between stages (see `docs/IMPLEMENTATION_PLAN.md` §1 and `neo4j/schema.cypher`).
  Renaming or removing one breaks downstream stages and the Cypher queries; update every reader in the same PR and note it in `TASKS.md`.
- **Idempotent loads.** Writes to Neo4j use `MERGE` on a unique key and stamp `source` and `run_id`. Keep it that way so anyone can re-run any stage.
- **Shared Neo4j instance.** If the team points at one database, do not run destructive Cypher (`DETACH DELETE`, dropping constraints, wiping a label) without telling the others.
- **Secrets and big files stay out of git.** `.env`, `data/`, `amendments/*.zst`, `neo4j/data/` are gitignored. Never `git add -A` blindly; check `git status` first.
- **LLM spend.** The LLM cache (`data/llm_cache.sqlite`) makes re-runs free; do not delete it casually. Changing a prompt or model in `.env` invalidates cached answers and costs money; say so in the PR.
- **Generated outputs.** `demo/*.html` are committed builds. Regenerate them only from a full, current run, in a separate commit.
