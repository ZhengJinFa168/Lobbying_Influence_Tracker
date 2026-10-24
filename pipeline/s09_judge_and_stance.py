"""S09 LLM judge (both tracks) and Track A stance coding, through OpenRouter (pipeline/llm.py).

Judge
- Input: ECHOED_IN pairs, organisation name hidden. Per track: every verbatim pair plus the top pairs by score,
  up to LLM_MAX_PAIRS_PER_TRACK (2,000).
- Output (JSON schema): llm_relation (implements | partial | contradicts | unrelated), llm_direction
  (strengthens | weakens | neutral: what the target does to the obligations/protections compared with the
  proposal or status quo, in the direction the lobby text asks), overlap_quote (from the target text).
- Tiers: T1 = verbatim and implements; T2 = implements, or verbatim and partial; T3 = everything else (incl.
  partial without a verbatim run). Until 2026-10-23 T2 was "verbatim, or implements / partial"; S10 reports that
  rule as a sensitivity check (query 02b).
  'unrelated' pairs stay in the graph with hidden = true.

Track A stance
- Issue codebook loaded from config (policy options of the inception impact assessment plus the recurring questions).
- Each Track A consultation comment is coded on every issue in one call per part (parts of <= ~4,500 words); a stance found
  in any part counts, conflicting parts become 'mixed'.
- Issue.proposal_choice is coded from the proposal text of the issue's articles (Provision nodes) by three
  models (LLM_MODEL, LLM_MODEL_SECOND, LLM_MODEL_HARD) and the majority is kept; disagreements are logged.
  (The plan's "3 seeded runs" give identical answers at temperature 0, and Anthropic endpoints ignore seeds,
  so three model families are the meaningful repeat.) Issues without proposal articles use the issue's outside_note: "not_addressed".
- TOOK_POSITION {stance, quote, aligned}.

Usage: python -m pipeline.run --only s09 [--track A|B]; env S09_LIMIT=n caps the judge pairs per track (dry runs).
"""
from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd

from . import config, graph, llm
from .judging import ISSUES, NA, code_comment, judge, judge_pairs, proposal_choices

PROCEDURE_AWARE = True  # reads wording, codebook and consultation feedback from config.PROC
log = logging.getLogger("s09")
SOURCE = "s09_judge_and_stance"
F = config.FEATURES

def tier(verbatim: bool, rel: str | None) -> str:
    # "partial" alone is not evidence: the judge gives it to ~1/3 of unrelated-law (null) pairs above tau_match
    # (S12 null check: AI Act 36.5%, DSA 30%), against 0-1% for "implements". So partial counts only with a verbatim run.
    # A verbatim run the judge calls contradicts or unrelated is not an echo either (T3).
    if verbatim and rel == "implements":
        return "T1"
    if rel == "implements" or (verbatim and rel == "partial"):
        return "T2"
    return "T3"


def run_judge(track: str) -> pd.DataFrame:
    pairs = judge_pairs(track)
    res = llm.batch(list(pairs.itertuples()), lambda r: judge(track, r))
    out = pd.DataFrame(res)
    pairs = pd.concat([pairs, out], axis=1)
    pairs["llm_model"] = config.LLM_MODEL
    ok = pairs.get("error").isna() if "error" in pairs else pd.Series(True, index=pairs.index)
    pairs["tier"] = [tier(v, r if k else None) for v, r, k in zip(pairs.verbatim, pairs.llm_relation, ok)]
    pairs["hidden"] = pairs.llm_relation.eq("unrelated")
    return pairs


def write_judgements(track: str, j: pd.DataFrame) -> None:
    label, key = ("Provision", "unit_id") if track == "A" else ("Amendment", "am_id")
    ok = j[j.llm_relation.notna()] if "llm_relation" in j else j.iloc[0:0]
    rows = ok[["chunk_id", "target_id", "llm_relation", "llm_direction", "overlap_quote", "tier", "hidden", "llm_model"]]
    graph.run(f"""
        UNWIND $rows AS r
        MATCH (:Chunk {{chunk_id: r.chunk_id}})-[e:ECHOED_IN]->(:{label} {{{key}: r.target_id}})
        SET e.llm_relation = r.llm_relation, e.llm_direction = r.llm_direction, e.overlap_quote = r.overlap_quote,
            e.tier = r.tier, e.hidden = r.hidden, e.llm_model = r.llm_model, e.judged_run_id = $run""",
              rows=rows.to_dict("records"), run=config.RUN_ID)


def run_stance() -> tuple[pd.DataFrame, pd.DataFrame]:
    issues = proposal_choices()
    if not ISSUES:
        return issues, pd.DataFrame()
    fb_rel = config.PROC.get("consultation", {}).get("A", {}).get("feedback") if isinstance(config.PROC.get("consultation"), dict) else None
    if not fb_rel or not (config.ROOT / fb_rel).is_file():
        log.info("Track A feedback file not found: %s", fb_rel)
        return issues, pd.DataFrame()
    recs = json.loads((config.ROOT / fb_rel).read_text(encoding="utf-8"))
    org_of = {r["fid"]: r["org"] for r in graph.run(
        "MATCH (o:Organisation)-[:SUBMITTED]->(c:Comment {track:'A'}) RETURN c.feedback_id AS fid, o.org_id AS org")}
    coded = llm.batch(recs, lambda r: code_comment(r.get("full_text") or ""))
    choice = issues.set_index("issue_id").proposal_choice
    rows = []
    for r, c in zip(recs, coded):
        if "error" in c:
            log.warning("stance failed for %s: %s", r["feedback_id"], c["error"])
            continue
        for iid, (stance, quote) in c.items():
            if stance == NA:
                continue
            rows.append(dict(start=org_of.get(str(r["feedback_id"])), end=iid, feedback_id=str(r["feedback_id"]),
                             stance=stance, quote=quote,
                             aligned=(stance == choice[iid]) if choice[iid] != NA and stance != "mixed" else None))
    return issues, pd.DataFrame(rows)


# ---------------------------------------------------------------- main
def main(track: str | None = None) -> None:
    print(f"   OpenRouter credit: {llm.credits()}")
    for t in ([track] if track else ["A", "B"]):
        j = run_judge(t)
        j.drop(columns=["chunk_text"]).to_parquet(config.CACHE / f"s09_judged_{t}.parquet", index=False)
        write_judgements(t, j)
        err = int(j["error"].notna().sum()) if "error" in j else 0
        print(f"   judge {t}: {len(j)} pairs, {err} errors; relations {j.llm_relation.value_counts().to_dict()}; "
              f"tiers {j.tier.value_counts().to_dict()}")
    if track in (None, "A"):
        cb_rel = config.PROC.get("stance", {}).get("codebook") if isinstance(config.PROC.get("stance"), dict) else None
        cb_file = config.ROOT / cb_rel if cb_rel else None
        if not cb_file or not cb_file.is_file() or not ISSUES:
            log.info("Track A stance coding skipped: codebook not found (%s)", cb_rel)
            return
        issues, pos = run_stance()
        if pos.empty:
            log.warning("Track A stance coding produced no positions; existing TOOK_POSITION edges are left as they are")
            return
        issues.to_parquet(config.CACHE / "s09_issues.parquet", index=False)
        pos.to_parquet(config.CACHE / "s09_positions.parquet", index=False)
        graph.merge_nodes("Issue", "issue_id", issues, SOURCE)
        graph.run("MATCH ()-[r:TOOK_POSITION]->() DELETE r")
        graph.merge_rels("TOOK_POSITION", "Organisation", "org_id", "Issue", "issue_id",
                         pos.dropna(subset=["start"]), SOURCE)
        print(f"   stance: {len(pos)} positions from {pos.feedback_id.nunique()} comments; "
              f"proposal choices {issues.set_index('issue_id').proposal_choice.to_dict()}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
