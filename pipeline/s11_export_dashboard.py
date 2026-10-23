"""S11 Export and dashboard.

- data/results/graph.json: the T1/T2 subgraph (organisations, amendments, provisions, MEPs, adopted amendments,
  law units and the edges between them), for Bloom-style exploration elsewhere.
- data/results/dashboard.html: one self-contained page (plotly.js inlined, data embedded) with KPI tiles, the reach
  funnel, a filterable organisation-article network, a Sankey, the pair viewer with "Judge this pair live",
  organisation cards, carriers, money vs influence, battlegrounds, the Track A issue heatmap, "Ask the graph"
  and the method / data-coverage box. Live buttons call pipeline/serve.py on localhost:8765; when it is not
  running they fall back to the cached verdicts and prepared queries.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd

from . import config, graph, sources

PROCEDURE_AWARE = True  # reads everything from config.PROC

log = logging.getLogger("s11")
R = config.RESULTS
TEMPLATE = Path(__file__).with_name("dashboard_template.html")
ECHO = "e.tier IN ['T1','T2'] AND NOT coalesce(e.hidden, false)"
N_PAIRS = 500


def _proc_info(dashboard: bool = True) -> dict:
    is_default = config.PROCEDURE_ID == config.DEFAULT_PROCEDURE
    proposal = config.PROC.get("texts", {}).get("proposal") or {}
    final = config.PROC.get("texts", {}).get("final") or {}
    parl = config.PROC.get("parliament") or {}
    report = parl.get("report") or {}
    shared = config.PROC.get("analysis", {}).get("shared_sources") or {}
    wording = config.PROC.get("wording") or {}
    consultation = config.PROC.get("consultation") or {}
    c_a = consultation.get("A") or {}
    c_b = consultation.get("B") or {}

    years = []
    for c_info in (c_a, c_b):
        if isinstance(c_info, dict) and c_info.get("label"):
            m = re.search(r"\b(20\d\d)\b", c_info["label"])
            if m and m.group(1) not in years:
                years.append(m.group(1))
    consultation_years = " + ".join(years) if years else ("2020 + 2021" if is_default else "")

    final_date = final.get("date") or ""
    final_year = final_date[:4] if final_date else ("2024" if is_default else "")

    report_date = report.get("date") or ""
    report_date_label = report_date
    if re.fullmatch(r"\d{4}-\d{2}", report_date):
        try:
            dt = datetime.strptime(report_date, "%Y-%m")
            report_date_label = dt.strftime("%B %Y")
        except Exception:
            pass

    null_proc = config.PROC.get("null_procedure") or ""
    null_short = "DSA" if is_default else ("AI Act" if null_proc == "2021/0106(COD)" else null_proc)

    final_act_coverage = (
        f"articles from the {final.get('consolidated_date')} consolidation (M1 changes flagged), recitals and \"as adopted\" text from the {final_year} OJ"
        if final.get("consolidated_date")
        else f"articles and recitals from the {final_year} OJ"
    )

    law = config.PROC.get("law") or ""
    law_short = law.replace("(EU) ", "") if "(EU) " in law else law

    m_a = re.search(r"\b(20\d\d)\b", c_a.get("label", "")) if isinstance(c_a, dict) else None
    m_b = re.search(r"\b(20\d\d)\b", c_b.get("label", "")) if isinstance(c_b, dict) else None

    return {
        "id": config.PROC.get("id"),
        "procedure": config.PROC.get("procedure"),
        "title": config.PROC.get("title"),
        "short": config.PROC.get("short"),
        "law": law,
        "law_short": law_short,
        "proposal_ref": proposal.get("ref"),
        "proposal_date": proposal.get("date"),
        "final_date": final_date,
        "final_year": final_year,
        "unit_prefix": final.get("unit_prefix"),
        "consolidated": final.get("consolidated"),
        "consolidated_date": final.get("consolidated_date"),
        "final_act_coverage": final_act_coverage,
        "report_id": report.get("id"),
        "report_date": report_date,
        "report_date_label": report_date_label,
        "rapporteurs": parl.get("rapporteurs") or [],
        "term": parl.get("term") or [],
        "null_procedure": null_proc,
        "null_short": null_short,
        "track_a_label": c_a.get("label") or ("2020 inception impact assessment" if is_default else "Track A"),
        "track_b_label": c_b.get("label") or ("2021 feedback on the proposal" if is_default else "Track B"),
        "track_a_short": "2020 inception (A)" if is_default else (c_a.get("label") or "Track A"),
        "track_b_short": "2021 proposal (B)" if is_default else (c_b.get("label") or "Track B"),
        "track_a_year": m_a.group(1) if m_a else "2020",
        "track_b_year": m_b.group(1) if m_b else "2021",
        "featured_article": (config.PROC.get("analysis") or {}).get("featured_article"),
        "shared_sources": shared.get("dashboard" if dashboard else "demo") or ("HLEG, OECD, White Paper" if is_default else ""),
        "topic": wording.get("topic") or ("AI" if is_default else config.PROC.get("short", "")),
        "consultation_years": consultation_years,
        "consultation_years_sub": consultation_years.replace(" + ", " and "),  # subtitle wording: "2020 and 2021"
        "base_amendments": config.PROC.get("expect", {}).get("committee_amendments"),
        "is_default": is_default,
    }


def csv(name: str) -> pd.DataFrame:
    p = R / f"{name}.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


def records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", force_ascii=False))


def article_of(uid: str) -> str:
    return uid.split("(")[0] if isinstance(uid, str) else uid


# ---------------------------------------------------------------- graph.json
def export_graph_json() -> dict:
    nodes, edges = {}, []

    def node(key, label, **props):
        nodes.setdefault(key, {"id": key, "label": label, **{k: v for k, v in props.items() if v is not None}})

    rows = graph.run(f"""
        MATCH (o:Organisation)-[:SUBMITTED]->(cm:Comment)<-[:PART_OF]-(c:Chunk)-[e:ECHOED_IN]->(t)
        WHERE {ECHO}
        RETURN o.org_id AS org, o.name AS org_name, o.user_type AS user_type, labels(t)[0] AS tl,
               coalesce(t.am_id, t.unit_id) AS tid, t.location AS location, t.survived AS survived,
               t.reached_law AS reached_law, cm.track AS track, count(e) AS n, max(e.score) AS score,
               collect(DISTINCT e.tier) AS tiers""")
    for r in rows:
        node(f"org:{r['org']}", "Organisation", name=r["org_name"], user_type=r["user_type"])
        node(f"{r['tl'].lower()}:{r['tid']}", r["tl"], name=r["tid"], location=r["location"], survived=r["survived"],
             reached_law=r["reached_law"])
        edges.append({"source": f"org:{r['org']}", "target": f"{r['tl'].lower()}:{r['tid']}", "type": "ECHOED_IN",
                      "track": r["track"], "chunks": r["n"], "score": r["score"], "tiers": r["tiers"]})
    ams = [n["name"] for n in nodes.values() if n["label"] == "Amendment"]
    for r in graph.run("""
        UNWIND $ams AS id MATCH (a:Amendment {am_id: id})
        OPTIONAL MATCH (a)-[:AMENDS]->(p:Provision)
        OPTIONAL MATCH (m:MEP)-[t:TABLED]->(a)
        OPTIONAL MATCH (a)-[:SURVIVED_AS]->(x:AdoptedAmendment)
        OPTIONAL MATCH (x)-[:BECAME]->(l:LegalUnit)
        RETURN id, p.unit_id AS p, collect(DISTINCT [m.mep_id, m.name, t.group, t.weight]) AS meps,
               x.adopted_id AS x, collect(DISTINCT l.law_unit_id) AS ls""", ams=ams):
        a = f"amendment:{r['id']}"
        if r["p"]:
            node(f"provision:{r['p']}", "Provision", name=r["p"])
            edges.append({"source": a, "target": f"provision:{r['p']}", "type": "AMENDS"})
        for mid, name, grp, w in r["meps"]:
            if mid is not None:
                node(f"mep:{mid}", "MEP", name=name, group=grp)
                edges.append({"source": f"mep:{mid}", "target": a, "type": "TABLED", "weight": w})
        if r["x"]:
            node(f"adopted:{r['x']}", "AdoptedAmendment", name=r["x"])
            edges.append({"source": a, "target": f"adopted:{r['x']}", "type": "SURVIVED_AS"})
            for lu in r["ls"]:
                node(f"law:{lu}", "LegalUnit", name=lu)
                edges.append({"source": f"adopted:{r['x']}", "target": f"law:{lu}", "type": "BECAME"})
    g = {"nodes": list(nodes.values()), "edges": edges,
         "meta": {"filter": "ECHOED_IN tier T1/T2, not hidden", "run_id": config.RUN_ID}}
    (R / "graph.json").write_text(json.dumps(g, ensure_ascii=False, default=str))
    return g


# ---------------------------------------------------------------- dashboard data
def tiles() -> list[dict]:
    c = graph.counts()
    e = graph.run(f"MATCH ()-[e:ECHOED_IN]->() WHERE {ECHO} RETURN count(e) AS n, "
                  "sum(CASE WHEN e.verbatim THEN 1 ELSE 0 END) AS v")[0]
    f = csv("02_reach_funnel")
    base = f[f.user_type.str.startswith("ALL")].iloc[0]
    info = _proc_info(dashboard=True)
    c_label = f"consultation comments ({info['consultation_years']})" if info["consultation_years"] else "consultation comments"
    final_yr = info["final_year"]
    l_label = f"of all amendments reached the {final_yr} law" if final_yr else "of all amendments reached the final law"
    return [
        {"v": f"{c['nodes'].get('Comment', 0):,}", "l": c_label},
        {"v": f"{c['nodes'].get('Organisation', 0):,}", "l": "organisations"},
        {"v": f"{c['nodes'].get('Amendment', 0):,}", "l": "committee amendments"},
        {"v": f"{e['n']:,}", "l": "judged echoes (T1/T2)"},
        {"v": f"{e['v']:,}", "l": "verbatim echoes (12+ identical words)"},
        {"v": f"{base.amendment_share_survived:.1%}", "l": "of all amendments survived into the EP report"},
        {"v": f"{base.amendment_share_reached_law:.1%}", "l": l_label},
    ]


def network() -> dict:
    rows = graph.run(f"""
        MATCH (o:Organisation)-[:SUBMITTED]->(cm:Comment)<-[:PART_OF]-(:Chunk)-[e:ECHOED_IN]->(t)
        WHERE {ECHO}
        WITH o, cm.track AS track, coalesce(t.unit_id, [(t)-[:AMENDS]->(p) | p.unit_id][0]) AS uid,
             e.tier AS tier, coalesce(t.reached_law, false) AS law
        RETURN o.org_id AS org, o.name AS name, o.user_type AS user_type, track, uid, tier, law, count(*) AS n""")
    df = pd.DataFrame(rows).dropna(subset=["uid"])
    df["article"] = df.uid.map(article_of)
    edges = df.groupby(["org", "article", "track", "tier", "law"], as_index=False).n.sum()
    G = nx.Graph()
    for r in edges.itertuples():
        G.add_edge(f"o:{r.org}", f"a:{r.article}", weight=float(r.n))
    pos = nx.spring_layout(G, k=1.4 / np.sqrt(max(len(G), 1)), iterations=200, seed=7, weight="weight")
    orgs = df.drop_duplicates("org").set_index("org")
    nodes = []
    for k, (x, y) in pos.items():
        kind, key = k.split(":", 1)
        if kind == "o":
            nodes.append(dict(id=k, kind="org", name=orgs.name[key], user_type=orgs.user_type[key], x=float(x), y=float(y)))
        else:
            nodes.append(dict(id=k, kind="article", name=key, x=float(x), y=float(y)))
    return {"nodes": nodes, "edges": records(edges.assign(source="o:" + edges.org, target="a:" + edges.article))}


def sankey() -> dict:
    rows = graph.run(f"""
        MATCH (o:Organisation)-[:SUBMITTED]->(:Comment {{track:'B'}})<-[:PART_OF]-(:Chunk)-[e:ECHOED_IN]->(a:Amendment)-[:AMENDS]->(p:Provision)
        WHERE {ECHO}
        RETURN DISTINCT o.name AS org, o.user_type AS user_type, coalesce(o.influence_b, 0) AS infl, a.am_id AS am,
               p.unit_id AS uid, a.survived AS survived, a.reached_law AS law""")
    df = pd.DataFrame(rows)
    top = df.groupby("org").infl.first().sort_values(ascending=False).head(20).index
    df = df[df.org.isin(top)].assign(article=lambda d: d.uid.map(article_of))
    keep = df.groupby("article").am.nunique().sort_values(ascending=False).head(15).index
    df = df.assign(article=lambda d: d.article.where(d.article.isin(keep), "other articles"),
                                     outcome=lambda d: np.where(d.law, "reached the law",
                                                                np.where(d.survived, "survived (EP report)", "dropped")))
    links = []
    for a, b in [("user_type", "org"), ("org", "article"), ("article", "outcome")]:
        g = df.groupby([a, b]).am.nunique().reset_index()
        links += [dict(s=f"{a}:{x}", t=f"{b}:{y}", v=int(v)) for x, y, v in g.itertuples(index=False)]
    labels = sorted({l["s"] for l in links} | {l["t"] for l in links})
    idx = {l: i for i, l in enumerate(labels)}
    return {"labels": [l.split(":", 1)[1] for l in labels], "kinds": [l.split(":", 1)[0] for l in labels],
            "source": [idx[l["s"]] for l in links], "target": [idx[l["t"]] for l in links],
            "value": [l["v"] for l in links]}


def pairs() -> list[dict]:
    out = []
    for track in ("B", "A"):
        p = config.CACHE / f"s09_judged_{track}.parquet"
        if not p.exists():
            continue
        j = pd.read_parquet(p)
        j = j[j.tier.isin(["T1", "T2"]) & ~j.hidden.fillna(False).astype(bool)]
        j = j.sort_values(["tier", "score"], ascending=[True, False]).head(N_PAIRS if track == "B" else 150)
        ch = pd.read_parquet(config.FEATURES / f"{track}_chunks.parquet").set_index("id").text
        meta = pd.DataFrame(graph.run("""
            UNWIND $ids AS id MATCH (c:Chunk {chunk_id: id})-[:PART_OF]->(cm:Comment)<-[:SUBMITTED]-(o:Organisation)
            RETURN id AS chunk_id, o.name AS org, o.user_type AS user_type, o.org_id AS org_id, cm.url AS url""",
                                      ids=j.chunk_id.unique().tolist()))
        j = j.merge(meta, on="chunk_id", how="left").assign(chunk_text=lambda d: d.chunk_id.map(ch), track=track)
        if track == "B":
            am = pd.DataFrame(graph.run("""
                UNWIND $ids AS id MATCH (a:Amendment {am_id: id})
                OPTIONAL MATCH (m:MEP)-[:TABLED {is_lead_author:true}]->(a)
                OPTIONAL MATCH (a)-[:SURVIVED_AS]->(x)-[:BECAME]->(l:LegalUnit)
                RETURN id AS target_id, a.survived AS survived, a.reached_law AS reached_law, m.name AS lead_mep,
                       collect(DISTINCT l.law_unit_id)[0] AS law_unit, a.committee AS committee""",
                                        ids=j.target_id.unique().tolist()))
            j = j.merge(am, on="target_id", how="left")
            ec = pd.DataFrame(graph.run("""
                UNWIND $p AS r MATCH (:Chunk {chunk_id: r[0]})-[e:ECHOED_IN]->(:Amendment {am_id: r[1]})
                RETURN r[0] AS chunk_id, r[1] AS target_id, e.carrier_met AS carrier_met""",
                                        p=j[["chunk_id", "target_id"]].values.tolist()))
            j = j.merge(ec, on=["chunk_id", "target_id"], how="left")
            j["target_text"] = j.added_text
        cols = ["track", "chunk_id", "target_id", "org", "org_id", "user_type", "url", "chunk_text", "target_text",
                "location", "old_text", "new_text", "score", "verbatim", "longest_run", "run_text", "tier",
                "llm_relation", "llm_direction", "overlap_quote", "survived", "reached_law", "lead_mep", "law_unit",
                "carrier_met"]
        out += records(j.reindex(columns=cols))
    return out


def organisations() -> list[dict]:
    rows = graph.run(f"""
        MATCH (o:Organisation)
        OPTIONAL MATCH (o)-[:SUBMITTED]->(cm:Comment)
        WITH o, collect(DISTINCT cm.track) AS tracks
        OPTIONAL MATCH (o)-[:SUBMITTED]->(:Comment)<-[:PART_OF]-(:Chunk)-[e:ECHOED_IN]->(t)
        WITH o, tracks, collect(e.tier) AS tiers, collect(DISTINCT CASE WHEN {ECHO} AND t:Amendment AND t.reached_law THEN t.am_id END) AS law_ams
        OPTIONAL MATCH (o)-[m:MET_WITH]->(mep:MEP)
        WITH o, tracks, tiers, law_ams, count(m) AS meetings, sum(CASE WHEN m.ai_related THEN 1 ELSE 0 END) AS ai_meetings,
             collect(DISTINCT mep.name)[0..12] AS meps_met
        OPTIONAL MATCH (o)-[p:TOOK_POSITION]->(i:Issue)
        RETURN o.org_id AS org_id, o.name AS name, o.user_type AS user_type, o.country AS country, tracks,
               o.match_method AS match_method, o.register_name AS register_name, o.lobbying_cost_eur AS cost,
               o.costs_is_range AS cost_range, o.fte AS fte, o.ep_passes_all AS ep_passes, o.ec_meetings_vdl1 AS ec_meetings,
               o.mep_meetings_all AS mep_meetings_register, o.reg_date AS reg_date, o.lobbyfacts_url AS lobbyfacts_url,
               coalesce(o.influence_b, 0) AS influence, o.coalition AS coalition,
               size([x IN tiers WHERE x = 'T1']) AS t1, size([x IN tiers WHERE x = 'T2']) AS t2,
               size([x IN tiers WHERE x = 'T3']) AS t3, size(law_ams) AS echoed_amendments_in_law,
               meetings, ai_meetings, meps_met, collect(i.issue_id + ': ' + p.stance) AS positions
        ORDER BY influence DESC""")
    return json.loads(json.dumps(rows, default=str))


def heatmap() -> dict:
    p = csv("08_track_a_positions")
    if p.empty:
        return {}
    p = p[p.aligned.notna()]
    p["aligned"] = p.aligned.astype(str).str.lower().eq("true")
    h = p.pivot_table(index="issue", columns="user_type", values="aligned", aggfunc="mean")
    n = p.pivot_table(index="issue", columns="user_type", values="aligned", aggfunc="size")
    return {"issues": list(h.index), "types": list(h.columns), "z": json.loads(h.round(3).to_json(orient="values")),
            "n": json.loads(n.reindex_like(h).fillna(0).astype(int).to_json(orient="values"))}


def coverage() -> dict:
    s06 = pd.read_parquet(config.CACHE / "s06_org_matches.parquet").drop_duplicates("org_id")
    met = graph.run("MATCH (o:Organisation) RETURN count(o) AS n, sum(CASE WHEN EXISTS { (o)-[:MET_WITH]->() } THEN 1 ELSE 0 END) AS met")[0]
    th = {}
    for f in ("s04_thresholds.json", "s08_thresholds.json"):
        p = config.DATA / f
        if p.exists():
            th[f.split("_")[0]] = json.loads(p.read_text())
    judged = {}
    for t in "AB":
        p = config.CACHE / f"s09_judged_{t}.parquet"
        if p.exists():
            judged[t] = int(len(pd.read_parquet(p)))
    return {
        "match_methods": dict(Counter(s06.match_method)),
        "orgs_with_meetings": met["met"], "orgs": met["n"],
        "thresholds": th, "judged_pairs": judged,
        "degraded_sources": sources.degraded(),
        "models": {"judge": config.LLM_MODEL, "second": config.LLM_MODEL_SECOND, "hard": config.LLM_MODEL_HARD,
                   "embeddings": config.EMBED_MODEL},
    }


def get_prepared() -> list[dict]:
    items = [
        dict(q="Which organisations' wording reached the final law most often?",
             cypher=f"""MATCH (o:Organisation)-[:SUBMITTED]->(:Comment)<-[:PART_OF]-(:Chunk)-[e:ECHOED_IN]->(a:Amendment)
WHERE {ECHO} AND a.reached_law
RETURN o.name AS organisation, o.user_type AS type, count(DISTINCT a) AS amendments_in_law
ORDER BY amendments_in_law DESC LIMIT 15"""),
        dict(q="Which MEPs tabled the most amendments echoing NGOs vs companies?",
             cypher=f"""MATCH (o:Organisation)-[:SUBMITTED]->(:Comment)<-[:PART_OF]-(:Chunk)-[e:ECHOED_IN]->(a:Amendment)<-[:TABLED]-(m:MEP)
WHERE {ECHO} AND o.user_type IN ['NGO','COMPANY']
RETURN m.name AS mep, o.user_type AS type, count(DISTINCT a) AS amendments
ORDER BY amendments DESC LIMIT 15"""),
    ]
    feat_art = (config.PROC.get("analysis") or {}).get("featured_article")
    if feat_art:
        art_label = re.sub(r"^Art(\d+)$", r"Article \1", feat_art) if feat_art.startswith("Art") else feat_art
        items.append(
            dict(q=f"Where do industry and NGOs pull {art_label} in opposite directions?",
                 cypher=f"""MATCH (o:Organisation)-[:SUBMITTED]->(:Comment)<-[:PART_OF]-(:Chunk)-[e:ECHOED_IN]->(a:Amendment)-[:AMENDS]->(p:Provision)
WHERE {ECHO} AND p.article = '{feat_art}' AND e.llm_direction IN ['strengthens','weakens']
RETURN p.unit_id AS provision, o.user_type AS type, e.llm_direction AS direction, count(*) AS echoes
ORDER BY provision, echoes DESC LIMIT 40""")
        )
    return items


PREPARED = get_prepared()


def build_data() -> dict:
    prepared = [dict(**p, rows=json.loads(json.dumps(graph.run(p["cypher"]), default=str))) for p in get_prepared()]
    return {
        "proc": _proc_info(dashboard=True),
        "tiles": tiles(),
        "funnel": records(csv("02_reach_funnel")),
        "network": network(),
        "sankey": sankey(),
        "pairs": pairs(),
        "orgs": organisations(),
        "carriers": records(csv("03_carriers").head(150)),
        "money": records(csv("12_org_money")),
        "money_stats": records(csv("money_vs_influence")),
        "battlegrounds": records(csv("07_battlegrounds").head(25)),
        "heatmap": heatmap(),
        "alignment": records(csv("track_a_alignment")),
        "access": records(csv("access_vs_echo")),
        "brokers": records(csv("05_mep_betweenness").head(15)),
        "coalitions": records(csv("06_coalitions")),
        "prepared": prepared,
        "coverage": coverage(),
    }


def main(track: str | None = None) -> None:
    g = export_graph_json()
    data = build_data()
    import plotly

    plotly_js = (Path(plotly.__file__).parent / "package_data" / "plotly.min.js").read_text()
    html = (TEMPLATE.read_text()
            .replace("__PLOTLYJS__", plotly_js)
            .replace("__DATA__", json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/")))
    out = R / "dashboard.html"
    out.write_text(html)
    print(f"   graph.json: {len(g['nodes']):,} nodes, {len(g['edges']):,} edges; dashboard.html "
          f"{out.stat().st_size / 1e6:.1f} MB ({len(data['pairs'])} pairs, {len(data['orgs'])} organisations)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
