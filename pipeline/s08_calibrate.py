"""S08 Calibration, then ECHOED_IN.

Null distribution: the same chunks go through the same candidate generation and scoring (S07) against an
unrelated procedure (config.NULL_PROCEDURE; e.g. for the AI Act, the Digital Services Act 2020/0361(COD))
committee amendments from the same ParlTrack dump (inserted words only, like Track B targets). This
unrelated digital file provides a strict null.
The plain shuffled null (random chunk-target pairs) is reported alongside for reference.
    tau_match = 99th percentile of the null candidate scores, per track.
Then every candidate with score >= tau_match, plus every verbatim pair, becomes
    (Chunk)-[:ECHOED_IN]->(Provision)   Track A
    (Chunk)-[:ECHOED_IN]->(Amendment)   Track B
with tier T3; S09 sets T1/T2 from the LLM judge's verdict (a verbatim run alone is not an echo tier).
Identical runs that also occur between the chunks and the null procedure are quotes of shared legal text (the
Charter's list of discrimination grounds, the GDPR definition of personal data); pairs whose run is such a quote
lose the verbatim flag (shared_legal_text = true).
Finally carrier_met is set on Track B echoes: did the organisation have a recorded MET_WITH with an MEP who
tabled the amendment ('2020', '2024', 'both' or null)?
"""
from __future__ import annotations

import json
import logging
import pickle
import re

import numpy as np
import pandas as pd
import scipy.sparse as sp

from . import config, graph, sources
from .embed import embed
from .s07_match import N, combine, load, masked, ngrams, pair_features, tri
from .s05_features import stoplist

# Procedure-aware: null procedure and paths loaded from config.PROC / config.NULL_PROCEDURE
PROCEDURE_AWARE = True

log = logging.getLogger("s08")
SOURCE = "s08_calibrate"
F = config.FEATURES


def null_targets() -> pd.DataFrame:
    """Committee amendments of the null procedure, inserted words only (same construction as S03's added_text)."""
    p = config.FEATURES / ("null_targets_" + re.sub(r"\W+", "_", config.NULL_PROCEDURE).strip("_") + ".parquet")
    if p.exists():
        return pd.read_parquet(p)
    legacy = config.FEATURES / "null_dsa_targets.parquet"
    if config.NULL_PROCEDURE == "2020/0361(COD)" and legacy.exists():
        df = pd.read_parquet(legacy)
        df.to_parquet(p, index=False)
        return df
    import importlib.util

    spec = importlib.util.spec_from_file_location("bd", config.ROOT / "amendments" / "build_dashboard.py")
    bd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bd)
    rows = []
    for r in sources.iter_zst_json(sources.path("parltrack_amendments"), json.dumps(config.NULL_PROCEDURE)):
        if r.get("reference") != config.NULL_PROCEDURE:
            continue
        old, new = bd.join_lines(r.get("old")), bd.join_lines(r.get("new"))
        if new.lower().rstrip(".") == "deleted":
            new = ""
        added = new if not old else bd.word_diff(old, new)[2]
        if added and added.split():
            rows.append(dict(id=r["id"], text=added))
    df = pd.DataFrame(rows)
    df.to_parquet(p, index=False)
    return df


def null_scores(track: str, G: pd.DataFrame, Ge: np.ndarray, Gx, stats: dict, common: set) -> pd.DataFrame:
    C, Ce, Cx = load(track, "chunks")
    stop = stoplist(track)
    c_tok = [masked(t, stop, common) for t in C.text]
    g_tok = [masked(t, stop, common) for t in G.text]
    g_tri = [tri(t) for t in g_tok]
    inv: dict[tuple, set[int]] = {}
    for j, toks in enumerate(g_tok):
        for g in ngrams([t if isinstance(t, str) else None for t in toks], N):
            if None not in g:
                inv.setdefault(g, set()).add(j)
    S = Ce @ Ge.T
    cand = set()
    for i in range(len(C)):
        cand.update((i, int(j)) for j in np.argpartition(-S[i], config.TOPK_EMBED)[: config.TOPK_EMBED])
        for g in ngrams([t if isinstance(t, str) else None for t in c_tok[i]], N):
            if None not in g:
                cand.update((i, j) for j in inv.get(g, ()))
    keys = sorted(cand)
    ii = np.array([k[0] for k in keys])
    jj = np.array([k[1] for k in keys])
    tf = np.asarray(Cx[ii].multiply(Gx[jj]).sum(axis=1)).ravel()
    rows = [dict(chunk_id=C.id.iat[i], target_id=G.id.iat[j], s_embed=float(S[i, j]), s_tfidf=float(t),
                 **pair_features(c_tok[i], g_tok[j], g_tri[j])) for (i, j), t in zip(keys, tf)]
    df = pd.DataFrame(rows)
    df["verbatim"] = df.longest_run >= config.VERBATIM_RUN
    df["score"] = combine(df, stats)
    return df


def carrier_met() -> None:
    graph.run("""
        MATCH (c:Chunk)-[e:ECHOED_IN]->(a:Amendment)
        MATCH (c)-[:PART_OF]->(:Comment)<-[:SUBMITTED]-(o:Organisation)
        OPTIONAL MATCH (o)-[m:MET_WITH]->(mep:MEP)-[:TABLED]->(a)
        WITH e, collect(DISTINCT m.period) AS periods
        SET e.carrier_met = CASE
            WHEN size(periods) = 0 THEN null
            WHEN size(periods) > 1 THEN 'both'
            ELSE periods[0] END""")


def main(track: str | None = None) -> None:
    stats = json.loads((F / "s07_random_stats.json").read_text())
    common = pickle.load(open(F / "common_quotes_12grams.pkl", "rb"))
    vec = pickle.load(open(F / "tfidf.pkl", "rb"))
    G = null_targets()
    Ge = embed(G.text.tolist())
    Gx = vec.transform(G.text.tolist()).tocsr()
    thresholds = {}
    available_tracks = [t for t in ("A", "B") if t in config.PUB_IDS and t in stats]
    if not available_tracks:
        available_tracks = [t for t in ("A", "B") if t in stats]
    if track and track not in available_tracks:
        raise SystemExit(f"S08: track {track} has no S07 statistics for {config.PROCEDURE_ID}")
    tracks = [track] if track else available_tracks
    del_match = "MATCH ()-[r:ECHOED_IN {track: $track}]->()" if track else "MATCH ()-[r:ECHOED_IN]->()"
    graph.run(f"{del_match} CALL {{ WITH r DELETE r }} IN TRANSACTIONS OF 10000 ROWS",
              **({"track": track} if track else {}))
    null_all = {t: null_scores(t, G, Ge, Gx, stats[t], common) for t in available_tracks}
    for t in tracks:
        null = null_all[t]
        null.to_parquet(config.CACHE / f"s08_null_{t}.parquet", index=False)
        tau = float(np.percentile(null.score, config.NULL_PERCENTILE))
        cand = pd.read_parquet(config.CACHE / f"s07_candidates_{t}.parquet")
        # shuffled null for reference: random chunk-target pairs of the track, scored the same way
        st = stats[t]
        rng = np.random.default_rng(1)
        Cc, Ce, Cx = load(t, "chunks")
        Gt, Gte, Gtx = load(t, "targets")
        i = rng.integers(0, len(Ce), 20000)
        j = rng.integers(0, len(Gte), 20000)
        sh = pd.DataFrame(dict(s_embed=np.einsum("ij,ij->i", Ce[i], Gte[j]),
                               s_tfidf=np.asarray(Cx[i].multiply(Gtx[j]).sum(axis=1)).ravel(), s_ngram=0.0))
        shuffled_99 = float(np.percentile(combine(sh, st), config.NULL_PERCENTILE))
        # identical runs that also occur between the chunks and the null procedure are quotes of shared legal text
        # (Charter Art 21's list of grounds, the GDPR definition of personal data): not evidence of an echo
        legal = {g for r in pd.concat([null_all[k] for k in null_all]).query("verbatim").run_text
                 for g in ngrams(r.split(), config.VERBATIM_RUN)}
        cand["shared_legal_text"] = [bool(v) and any(g in legal for g in ngrams((rt or "").split(), config.VERBATIM_RUN))
                                     for v, rt in zip(cand.verbatim, cand.run_text)]
        cand["verbatim"] = cand.verbatim & ~cand.shared_legal_text
        echo = cand[(cand.score >= tau) | cand.verbatim].copy()
        echo["tier"] = "T3"  # S09 sets T1/T2 from the judge's verdict
        thresholds[t] = dict(tau_match=tau, null_pairs=len(null), null_verbatim=int(null.verbatim.sum()),
                             null_verbatim_rate=float(null.verbatim.mean()), shuffled_null_99=shuffled_99,
                             candidates=len(cand), echoes=len(echo), echoes_verbatim=int(echo.verbatim.sum()),
                             candidates_above_tau=int((cand.score >= tau).sum()),
                             verbatim_downgraded_shared_legal_text=int(cand.shared_legal_text.sum()))
        echo.to_parquet(config.CACHE / f"s08_echoes_{t}.parquet", index=False)
        label, key = ("Provision", "unit_id") if t == "A" else ("Amendment", "am_id")
        rel = echo.rename(columns={"chunk_id": "start", "target_id": "end"})
        graph.merge_rels("ECHOED_IN", "Chunk", "chunk_id", label, key,
                         rel[["start", "end", "track", "score", "s_embed", "s_tfidf", "s_ngram", "longest_run",
                              "run_text", "verbatim", "shared_legal_text", "tier", "candidate_sources"]], SOURCE)
        print(f"   track {t}: tau_match={tau:.2f} (null {config.NULL_PROCEDURE}, {len(null):,} pairs; shuffled-pair null 99th = "
              f"{shuffled_99:.2f}); null verbatim {int(null.verbatim.sum())} ({null.verbatim.mean():.3%}); "
              f"ECHOED_IN {len(echo):,} ({int(echo.verbatim.sum())} verbatim) from {echo.chunk_id.nunique():,} chunks")
    carrier_met()
    (config.DATA / "s08_thresholds.json").write_text(json.dumps(thresholds, indent=2))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
