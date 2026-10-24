"""LLM judge and Track A codebook shared by S09, S10, S12 and the live proxy (serve.py): judge prompts and schema,
the pair selection, the codebook loaded from the procedure config, stance and proposal-choice prompts.
Moved verbatim out of s09_judge_and_stance (prompt strings unchanged: they are LLM cache keys).
"""
from __future__ import annotations

import json
import logging
import os
from collections import Counter

import pandas as pd
import yaml

from . import config, llm

log = logging.getLogger("s09")
F = config.FEATURES

# ---------------------------------------------------------------- judge
JUDGE_SYSTEM = ("You compare a passage from a stakeholder's consultation submission with a piece of EU legislative "
                "text. Judge only what the texts say. Answer with JSON matching the schema.")
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "llm_relation": {"type": "string", "enum": ["implements", "partial", "contradicts", "unrelated"]},
        "llm_direction": {"type": "string", "enum": ["strengthens", "weakens", "neutral"]},
        "overlap_quote": {"type": "string"},
    },
    "required": ["llm_relation", "llm_direction", "overlap_quote"],
    "additionalProperties": False,
}
_WORDING = config.PROC.get("wording", {}) if isinstance(config.PROC.get("wording"), dict) else {}
_TOPIC = _WORDING.get("topic", "AI")
JUDGE_PROMPT = """STAKEHOLDER PASSAGE (consultation submission):
\"\"\"{chunk}\"\"\"

LEGISLATIVE TEXT ({target_kind}):
{target}

Questions:
1. llm_relation: does the legislative text put into effect what the stakeholder passage asks for or proposes?
   - "implements": it does what the passage asks, in substance (wording may differ)
   - "partial": it goes some of the way, or does one of several things asked
   - "contradicts": it does the opposite of what the passage asks
   - "unrelated": it addresses something else, or the overlap is only a shared topic or a common quotation
2. llm_direction: compared with {baseline}, does the legislative text make the rules on """ + _TOPIC + """ stricter or more
   protective ("strengthens"), looser or less burdensome ("weakens"), or neither ("neutral")?
3. overlap_quote: the shortest quote (max 30 words) from the LEGISLATIVE TEXT that matches the passage;
   empty string if unrelated."""


def _target_block(track: str, row) -> tuple[str, str, str]:
    if track == "A":
        target_kind = _WORDING.get("judge_target_A", "a provision of the Commission's 2021 proposal")
        return target_kind, f"[{row.target_id}] {row.target_text}", \
            "the situation before this proposal"
    old = row.old_text if isinstance(row.old_text, str) and row.old_text else "(new provision)"
    target_kind = _WORDING.get("judge_target_B", "a European Parliament committee amendment to the 2021 proposal")
    return (target_kind,
            f"Provision: {row.location}\nProposal text: {old}\nAmended text: {row.new_text}\n"
            f"Words the amendment inserts: {row.added_text}", "the Commission's proposal text")


def judge_prompt(track: str, row) -> str:
    kind, target, baseline = _target_block(track, row)
    return JUDGE_PROMPT.format(chunk=row.chunk_text, target_kind=kind, target=target, baseline=baseline)


def judge(track: str, row, model: str | None = None) -> dict:
    kw = dict(system=JUDGE_SYSTEM, max_tokens=config.JUDGE_MAX_TOKENS, tag=f"judge_{track}")
    try:
        return llm.complete(judge_prompt(track, row), JUDGE_SCHEMA, model=model, **kw)
    except llm.LLMError:
        if model is not None:
            raise
        # the main model returned invalid JSON twice: fall back to the hard-case model for this pair
        return {**llm.complete(judge_prompt(track, row), JUDGE_SCHEMA, model=config.LLM_MODEL_HARD, **kw),
                "fallback_model": config.LLM_MODEL_HARD}


def judge_pairs(track: str) -> pd.DataFrame:
    e = pd.read_parquet(config.CACHE / f"s08_echoes_{track}.parquet")
    limit = int(os.getenv("S09_LIMIT", config.LLM_MAX_PAIRS_PER_TRACK))
    pick = pd.concat([e[e.verbatim], e[~e.verbatim].sort_values("score", ascending=False)]).head(limit)
    ch = pd.read_parquet(F / f"{track}_chunks.parquet").set_index("id").text
    pick = pick.assign(chunk_text=pick.chunk_id.map(ch))
    if track == "A":
        t = pd.read_parquet(F / "A_targets.parquet").set_index("id").text
        pick = pick.assign(target_text=pick.target_id.map(t))
    else:
        a = pd.read_parquet(config.CACHE / "s03_amendments.parquet").set_index("am_id")
        pick = pick.join(a[["location", "old_text", "new_text", "added_text"]], on="target_id")
    return pick.reset_index(drop=True)


# ---------------------------------------------------------------- Track A issues
def _load_codebook() -> tuple[list[dict], dict[str, str]]:
    cb_rel = config.PROC.get("stance", {}).get("codebook") if isinstance(config.PROC.get("stance"), dict) else None
    if not cb_rel:
        return [], {}
    p = config.ROOT / cb_rel
    if not p.is_file():
        return [], {}
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    raw_issues = data.get("issues", []) if isinstance(data, dict) else []
    issues = []
    outside_notes = {}
    for item in raw_issues:
        issues.append({
            "issue_id": item["issue_id"],
            "label": item["label"],
            "choices": list(item["choices"]),
            "articles": list(item["articles"]),
        })
        if "outside_note" in item:
            outside_notes[item["issue_id"]] = item["outside_note"]
    return issues, outside_notes


ISSUES, _OUTSIDE_NOTES = _load_codebook()
NA = "not_addressed"


def stance_schema() -> dict:
    props = {}
    for i in ISSUES:
        props[i["issue_id"]] = {
            "type": "object",
            "properties": {"stance": {"type": "string", "enum": i["choices"] + [NA]}, "quote": {"type": "string"}},
            "required": ["stance", "quote"], "additionalProperties": False}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def codebook_text() -> str:
    return "\n".join(f"- {i['issue_id']}: {i['label']}. Choices: {', '.join(i['choices'])}, or {NA}." for i in ISSUES)


_STANCE_CONSULTATION = _WORDING.get("stance_consultation",
                                    "the European Commission's 2020 consultation on an AI regulation (inception impact assessment)")
STANCE_SYSTEM = ("You code the positions a stakeholder takes in a submission to "
                 f"{_STANCE_CONSULTATION}. Code only positions the text states. "
                 "Answer with JSON matching the schema.")
STANCE_PROMPT = """Codebook (one stance per issue; use "{na}" when the text takes no position):
{codebook}

For each issue give the stance and a supporting quote of at most 30 words from the text (empty if {na}).

SUBMISSION TEXT (part {part} of {parts}):
\"\"\"{text}\"\"\""""
_PROPOSAL_PROMPT_TARGET = _WORDING.get("proposal_prompt", "the European Commission's 2021 AI Act proposal")
PROPOSAL_PROMPT = """Codebook issue: {label}. Choices: {choices}.

Below is the relevant text of """ + _PROPOSAL_PROMPT_TARGET + """. Which choice does the proposal make?
Give the choice, the article you relied on, and a quote of at most 30 words.

{text}"""


def parts(text: str, max_words: int = 4500) -> list[str]:
    w = text.split()
    return [" ".join(w[i : i + max_words]) for i in range(0, len(w), max_words)] or [""]


def code_comment(text: str) -> dict:
    pieces = parts(text)
    def one(k: int, p: str) -> dict:
        prompt = STANCE_PROMPT.format(na=NA, codebook=codebook_text(), part=k + 1, parts=len(pieces), text=p)
        kw = dict(system=STANCE_SYSTEM, max_tokens=config.STANCE_MAX_TOKENS, tag="stance")
        try:
            return llm.complete(prompt, stance_schema(), **kw)
        except llm.LLMError:  # invalid JSON twice: fall back to the hard-case model
            return llm.complete(prompt, stance_schema(), model=config.LLM_MODEL_HARD, **kw)

    res = [one(k, p) for k, p in enumerate(pieces)]
    out = {}
    for i in ISSUES:
        found = [(r[i["issue_id"]]["stance"], r[i["issue_id"]]["quote"]) for r in res if r[i["issue_id"]]["stance"] != NA]
        stances = {s for s, _ in found}
        out[i["issue_id"]] = (("mixed" if len(stances) > 1 else found[0][0]), found[0][1]) if found else (NA, "")
    return out


def proposal_choices() -> pd.DataFrame:
    if not ISSUES:
        return pd.DataFrame(columns=["issue_id", "label", "proposal_choice", "article_ref", "proposal_quote", "votes", "agreement"])
    prov = pd.read_parquet(config.CACHE / "s02_proposal_units.parquet")
    rows = []
    for i in ISSUES:
        if not i["articles"]:
            note = _OUTSIDE_NOTES.get(i["issue_id"], f"{i['issue_id']} is outside the {config.PROC.get('short', 'act')}")
            rows.append(dict(issue_id=i["issue_id"], label=i["label"], proposal_choice=NA, article_ref=None,
                             proposal_quote=None, votes=note, agreement=1.0))
            continue
        txt = "\n\n".join(f"[{a}] " + prov[prov.article == a].full_text.iloc[0][:6000]
                          for a in i["articles"] if (prov.article == a).any() and (prov.unit_id == a).any())
        schema = {"type": "object", "properties": {
            "choice": {"type": "string", "enum": i["choices"]}, "article": {"type": "string"}, "quote": {"type": "string"}},
            "required": ["choice", "article", "quote"], "additionalProperties": False}
        prompt = PROPOSAL_PROMPT.format(label=i["label"], choices=", ".join(i["choices"]), text=txt)
        votes = [llm.complete(prompt, schema, model=m, max_tokens=config.STANCE_MAX_TOKENS, tag="proposal_choice")
                 for m in (config.LLM_MODEL, config.LLM_MODEL_SECOND, config.LLM_MODEL_HARD)]
        c = Counter(v["choice"] for v in votes)
        choice, n = c.most_common(1)[0]
        best = next(v for v in votes if v["choice"] == choice)
        if n < 3:
            log.warning("proposal_choice %s: models disagree %s", i["issue_id"], dict(c))
        rows.append(dict(issue_id=i["issue_id"], label=i["label"], proposal_choice=choice, article_ref=best["article"],
                         proposal_quote=best["quote"], votes=json.dumps(dict(c)), agreement=n / 3))
    return pd.DataFrame(rows)
