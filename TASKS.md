# TASKS

Task board for who owns what. **Claim a row before editing a module**, commit the change to this file, and update the status as you go.
Rules are in `CLAUDE.md` → *Multi-developer safety*.

Status: `Todo` · `In progress` · `In review` · `Blocked` · `Done`

## Active work

| Task | Module / files | Owner | Branch | Status | Notes |
|---|---|---|---|---|---|
| _example: tighten org name matching_ | `pipeline/s06_orgs.py` | _name_ | `feat/org-matching` | Todo | _touches graph contract? y/n_ |
| Agent guardrails: Tach boundaries, guard hook, CODEOWNERS, CI | `tach.toml`, `.pre-commit-config.yaml`, `.github/`, `.claude/`, `CLAUDE.md`, `TASKS.md`, `requirements-dev.txt` | Luigi Zheng | `chore/agent-guardrails` | In progress | graph contract: n; no pipeline code changed |
| DSA step 0: per-procedure config format, AI Act literal audit, separate DSA Neo4j | `data_sources/procedures/`, `neo4j/docker-compose.dsa.yml`, docs only (no stage code yet) | Luigi Zheng | `feat/dsa-step0` | Done | graph contract: n (`MET_WITH.ai_related` kept as "about this procedure" for the DSA dry run); format approved 2026-10-23 |
| Wire per-procedure config: `config.py` loads `data_sources/procedures/<id>.yaml`, `run.py --procedure` | `pipeline/config.py`, `pipeline/run.py` (shared hotspots) | Luigi Zheng | `feat/dsa-step0` | Done | default `ai_act`, all existing config values unchanged; stages not touched. A stage opts in to other procedures with `PROCEDURE_AWARE = True` |
| | | | | | |

## Module owners

Default point of contact per area. Anyone may work on a module, but tell its owner first.

| Module | Files | Owner |
|---|---|---|
| Scraping and feedback | `WebScraping/`, `pipeline/s01_feedback.py` | |
| Legal texts | `pipeline/s02_legal_texts.py`, `pipeline/units.py`, `data_sources/eurlex/` | |
| Amendments and survival | `amendments/`, `pipeline/s03_amendments.py`, `pipeline/s04_survival.py` | |
| Features and matching | `pipeline/s05_features.py`, `pipeline/embed.py`, `pipeline/s07_match.py`, `pipeline/s08_calibrate.py` | |
| Organisations and meetings | `pipeline/s06_orgs.py`, `pipeline/s06b_meetings.py`, `data_sources/lobbyfacts/`, `data_sources/integritywatch/` | |
| LLM judge and stance | `pipeline/llm.py`, `pipeline/s09_judge_and_stance.py`, `pipeline/s12_eval.py` | |
| Graph schema and analysis | `neo4j/`, `pipeline/graph.py`, `pipeline/s10_analyse.py`, `pipeline/s10b_reach_model.py` | |
| Dashboard and demo | `pipeline/s11_export_dashboard.py`, `pipeline/s11b_demo.py`, `pipeline/*_template.html`, `pipeline/serve.py`, `demo/` | |
| Shared core | `pipeline/config.py`, `pipeline/run.py`, `pipeline/sources.py`, `requirements.txt` | |

## Boundary debt

Cross-stage imports that break the rule "a stage's only public name is `main()`" (`tach check` fails until they are gone).
Fix by moving the shared code into a shared module (`textutil`, `units`, a new `pipeline/<name>.py` utility added to `tach.toml` with approval)
or by reading the data from Neo4j / `config.py` paths. Claim a row before starting.

| Importer | Imports | From | Suggested home | Owner | Status |
|---|---|---|---|---|---|
| `pipeline/s06b_meetings.py:26` | `_acronym`, `mnorm` | `s06_orgs` | org-name helpers into `textutil` (or new `orgnames.py`) | | Todo |
| `pipeline/s07_match.py:33` | `N`, `ngram_tokens`, `ngrams`, `stoplist`, `tokens` | `s05_features` | new shared `ngrams.py` | | Todo |
| `pipeline/s08_calibrate.py:30-31` | `N`, `combine`, `load`, `masked`, `ngrams`, `pair_features`, `tri`; `stoplist` | `s07_match`, `s05_features` | new shared `matching.py` / `ngrams.py` | | Todo |
| `pipeline/s10_analyse.py:83` | `ISSUES` | `s09_judge_and_stance` | constant into `config.py` | | Todo |
| `pipeline/s11b_demo.py:20` | `RAPPORTEURS` | `s10b_reach_model` | constant into `config.py` | | Todo |
| `pipeline/s12_eval.py:23` | `judge`, `proposal_choices`, `_parts`, `_codebook`, `_stance_schema`, `NA`, `STANCE_PROMPT`, `STANCE_SYSTEM` | `s09_judge_and_stance` | new shared `judge.py` (prompts, schema, judge) | | Todo |
| `pipeline/serve.py:22` | whole module (`judge_pairs`, `judge_prompt`, `JUDGE_SCHEMA`, `JUDGE_SYSTEM`) | `s09_judge_and_stance` | same `judge.py` | | Todo |

## Graph contract changes

Log any change to node labels, relationship types or properties so downstream owners can update their stages and queries.

| Date | Change | Stages / queries affected | Who | PR |
|---|---|---|---|---|
| | | | | |

## Done

| Task | Owner | PR | Date |
|---|---|---|---|
| | | | |
