"""S11b Demo app: data/results/demo.html, a multi-page, self-contained story of who influenced the act.

Pages (hash routes): #/ pick the act and see the headline · #/lobbies top influencers · #/lobby/<id> profile
(money, meetings, interests, statements, where their wording went) · #/story/<n> one comment followed through
amendment, EP report and final law, with the reach probability and why · #/mep/<id> the politicians who carried
it (party, committees, outside activities, meetings, track record) · #/influence pre-bill vs bill influence and
the reach model · #/method data and caveats.
Only the AI Act (2021/0106(COD)) is processed; other acts are listed as "not processed yet".
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, graph, sources

PROCEDURE_AWARE = True  # reads everything from config.PROC

log = logging.getLogger("s11b")
R = config.RESULTS
TEMPLATE = Path(__file__).with_name("demo_template.html")
ECHO = "e.tier IN ['T1','T2'] AND NOT coalesce(e.hidden, false)"
RAPPORTEURS = set((config.PROC.get("parliament") or {}).get("rapporteurs") or [])
TERM = tuple((config.PROC.get("parliament") or {}).get("term") or ["2019-07-02", "2024-07-15"])


def _term_leg(term: tuple | list) -> str:
    if term and len(term) >= 1 and str(term[0]).startswith("2019"):
        return "LEG9"
    try:
        y = int(str(term[0])[:4])
        return f"LEG{9 + (y - 2019) // 5}"
    except Exception:
        return "LEG9"


LEG = _term_leg(TERM)


def _format_day_month_year(d_str: str) -> str:
    """Format 'YYYY-MM-DD' as '13 June 2024'."""
    if not d_str:
        return ""
    try:
        dt = datetime.strptime(d_str[:10], "%Y-%m-%d")
        return f"{dt.day} {dt.strftime('%B %Y')}"
    except Exception:
        return d_str


def _format_month_year(d_str: str) -> str:
    """Format 'YYYY-MM' or 'YYYY-MM-DD' as 'June 2023' or 'April 2021'."""
    if not d_str:
        return ""
    try:
        dt = datetime.strptime(d_str[:7], "%Y-%m")
        return dt.strftime("%B %Y")
    except Exception:
        return d_str


_ALL_KNOWN_ACTS = [
    dict(id="2021/0106(COD)", name="Artificial Intelligence Act", short="AI Act", law="Regulation (EU) 2024/1689"),
    dict(id="2020/0361(COD)", name="Digital Services Act", short="DSA", law="Regulation (EU) 2022/2065"),
    dict(id="2020/0374(COD)", name="Digital Markets Act", short="DMA", law="Regulation (EU) 2022/1925"),
    dict(id="2022/0140(COD)", name="European Health Data Space", short="EHDS", law="Regulation (EU) 2025/327"),
]


def _build_acts() -> list[dict]:
    curr_proc = config.PROC["procedure"]
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

    prop_date = proposal.get("date") or ""
    prop_year = prop_date[:4] if prop_date else ("2021" if is_default else "")
    prop_month_year = _format_month_year(prop_date) if prop_date else ("April 2021" if is_default else "")

    final_date = final.get("date") or ""
    final_year = final_date[:4] if final_date else ("2024" if is_default else "")
    final_date_label = _format_day_month_year(final_date) if final_date else ("13 June 2024" if is_default else "")

    report_date = report.get("date") or ""
    report_date_label = _format_month_year(report_date) if report_date else ("June 2023" if is_default else "")
    report_year = report_date[:4] if report_date else ("2023" if is_default else "")

    term = parl.get("term") or ["2019-07-02", "2024-07-15"]
    term_start = str(term[0])[:4] if term and len(term) >= 1 else "2019"
    term_end = str(term[1])[:4] if term and len(term) >= 2 else "2024"
    term_years = f"{term_start}–{term_end}"

    null_proc = config.PROC.get("null_procedure") or ""
    null_short = "DSA" if is_default else ("AI Act" if null_proc == "2021/0106(COD)" else null_proc)
    null_short_label = f"the {null_short}"

    consolidated_label = (
        f" (as adopted + {final.get('consolidated_date')[:4]} consolidation)"
        if final.get("consolidated_date")
        else (" (as adopted + 2026 consolidation)" if is_default else " (as adopted)")
    )

    m_a = re.search(r"\b(20\d\d)\b", c_a.get("label", "")) if isinstance(c_a, dict) else None
    m_b = re.search(r"\b(20\d\d)\b", c_b.get("label", "")) if isinstance(c_b, dict) else None
    t_a_year = m_a.group(1) if m_a else "2020"
    t_b_year = m_b.group(1) if m_b else "2021"

    amendment_year = "2022" if is_default else (t_b_year or "2021")

    moments_lead = (
        f"<p class=\"lead\">Two moments to influence a law: <b>before the bill</b>, when the Commission drafts it "
        f"({t_a_year} inception consultation → {prop_year} proposal), and <b>on the bill</b>, when Parliament amends it "
        f"({t_b_year} comments → {amendment_year} committee amendments → {report_year} report → {final_year} law).</p>"
    )

    curr = dict(
        id=curr_proc,
        name=config.PROC["title"],
        short=config.PROC["short"],
        law=config.PROC["law"],
        ready=True,
        procedure=curr_proc,
        title=config.PROC.get("title"),
        proposal_ref=proposal.get("ref"),
        proposal_date=prop_date,
        proposal_year=prop_year,
        proposal_month_year=prop_month_year,
        final_date=final_date,
        final_year=final_year,
        final_date_label=final_date_label,
        unit_prefix=final.get("unit_prefix"),
        consolidated=final.get("consolidated"),
        consolidated_date=final.get("consolidated_date"),
        consolidated_label=consolidated_label,
        report_id=report.get("id"),
        report_date=report_date,
        report_date_label=report_date_label,
        report_year=report_year,
        rapporteurs=parl.get("rapporteurs") or [],
        term=term,
        term_years=term_years,
        term_start_year=term_start,
        null_procedure=null_proc,
        null_short=null_short,
        null_short_label=null_short_label,
        track_a_label=c_a.get("label") or ("2020 inception impact assessment" if is_default else "Track A"),
        track_b_label=c_b.get("label") or ("2021 feedback on the proposal" if is_default else "Track B"),
        track_a_short="2020 inception comment" if is_default else (c_a.get("label") or "Track A comment"),
        track_b_short="2021 proposal comment" if is_default else (c_b.get("label") or "Track B comment"),
        track_a_comment_title="2020 inception comment" if is_default else f"{t_a_year} inception comment",
        track_b_comment_title="2021 comment on the proposal" if is_default else f"{t_b_year} comment on the proposal",
        track_a_year=t_a_year,
        track_b_year=t_b_year,
        amendment_year=amendment_year,
        consultation_sub=f"{t_a_year} inception + {t_b_year} proposal" if (t_a_year and t_b_year) else "consultation comments",
        consultation_sources=(
            "2020 inception impact assessment, 2021 proposal"
            if is_default
            else (
                f"{c_a.get('label') or 'Track A'}, {c_b.get('label') or 'Track B'}"
                if c_a and c_b
                else (c_a.get("label") or c_b.get("label") or "consultation")
            )
        ),
        featured_article=(config.PROC.get("analysis") or {}).get("featured_article"),
        shared_sources=shared.get("demo") or ("the HLEG guidelines, the OECD definition, the White Paper" if is_default else ""),
        topic=wording.get("topic") or ("AI" if is_default else config.PROC.get("short", "")),
        moments_lead=moments_lead,
        meeting_caveat=(
            "Meeting records cover 2020 and June–October 2024 only; nothing covers the 2022–2023 amendment period."
            if is_default
            else "Meeting records cover 2020 and June–October 2024 only; data for other periods is not recorded."
        ),
        search_hint="try “Art 5”, “Twilio”, “Benifei”, “Greens”" if is_default else "try “Article”, “Company”, “MEP”, “Group”",
        filter_placeholder="Filter: “Article 5”, “biometric”, “sandbox”…" if is_default else "Filter by keyword…",
        register_year="2026" if is_default else "",
        is_default=is_default,
    )
    others = [dict(**a, ready=False) for a in _ALL_KNOWN_ACTS if a["id"] != curr_proc]
    return [curr] + others


ACTS = _build_acts()


def _clean(x):
    if isinstance(x, float) and (x != x or x in (float("inf"), float("-inf"))):
        return None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, np.generic):
        return _clean(x.item())
    return x


def J(x):
    """JSON-safe copy: NaN/inf -> null (JSON.parse rejects NaN), numpy scalars -> Python."""
    return json.loads(json.dumps(_clean(x), default=str, ensure_ascii=False))


def csvr(name: str) -> list[dict]:
    p = R / f"{name}.csv"
    return J(pd.read_csv(p).to_dict("records")) if p.exists() else []


# ---------------------------------------------------------------- MEPs
def mep_profiles(ids: set[int]) -> dict:
    out = {}
    for r in sources.iter_zst_json(sources.path("parltrack_meps")):
        uid = r.get("UserID")
        if uid is None or int(uid) not in ids:
            continue

        def in_term(x):
            return (x.get("start", "") or "") <= TERM[1] and (x.get("end") or "9999") >= TERM[0]

        cons = [c for c in r.get("Constituencies") or [] if c and in_term(c)]
        groups = [g for g in r.get("Groups") or [] if g and in_term(g)]
        comms = [c for c in r.get("Committees") or [] if c and in_term(c)]
        fin = [f for f in r.get("Financial Declarations") or [] if LEG in (f.get("url") or "")]
        occ = []
        if fin:
            f = fin[-1]
            for k in ("occupation", "activity", "mandate", "membership"):
                for item in f.get(k) or []:
                    name = item[0] if isinstance(item, list) else item
                    if isinstance(name, str) and name.strip() and name.strip() != "MEP":
                        occ.append(" ".join(name.split()))
        out[int(uid)] = dict(
            name=(r.get("Name") or {}).get("full"), photo=r.get("Photo"), gender=r.get("Gender"),
            birth_year=((r.get("Birth") or {}).get("date") or "")[:4] or None,
            country=cons[-1].get("country") if cons else None, party=cons[-1].get("party") if cons else None,
            groups=list(dict.fromkeys(g.get("groupid") for g in groups if g.get("groupid"))),
            group_names=list(dict.fromkeys(g.get("Organization") for g in groups)),
            committees=[dict(abbr=c.get("abbr"), name=c.get("Organization"), role=c.get("role")) for c in comms],
            homepage=(r.get("Homepage") or [None])[0], x=(r.get("X") or r.get("Twitter") or [None])[0],
            ep_url=(r.get("meta") or {}).get("url"), outside_activities=occ[:12], active=r.get("active"))
    return out


def meps(lobby_mep_ids: set[int]) -> dict:
    stats = {r["id"]: r for r in graph.run("""
        MATCH (m:MEP)-[t:TABLED]->(a:Amendment)
        RETURN m.mep_id AS id, count(a) AS tabled, sum(CASE WHEN t.is_lead_author THEN 1 ELSE 0 END) AS lead,
               sum(CASE WHEN a.survived THEN 1 ELSE 0 END) AS survived, sum(CASE WHEN a.reached_law THEN 1 ELSE 0 END) AS law,
               collect(DISTINCT t.group)[0] AS group_at_tabling, collect(DISTINCT a.committee) AS committees""")}
    echoes = graph.run(f"""
        MATCH (o:Organisation)-[:SUBMITTED]->(:Comment)<-[:PART_OF]-(:Chunk)-[e:ECHOED_IN]->(a:Amendment)<-[:TABLED]-(m:MEP)
        WHERE {ECHO}
        RETURN m.mep_id AS id, o.org_id AS org, o.name AS name, o.user_type AS type, count(DISTINCT a) AS amendments,
               sum(CASE WHEN a.reached_law THEN 1 ELSE 0 END) AS law ORDER BY amendments DESC""")
    meets = graph.run("""
        MATCH (o:Organisation)-[r:MET_WITH]->(m:MEP)
        RETURN m.mep_id AS id, o.org_id AS org, o.name AS name, r.date AS date, r.title AS title, r.mep_role AS role,
               r.ai_related AS ai ORDER BY r.date""")
    names = {r["id"]: r for r in graph.run("MATCH (m:MEP) RETURN m.mep_id AS id, m.name AS name, m.country AS country, m.iw_group AS iw_group")}
    ids = set(stats) | lobby_mep_ids
    prof = mep_profiles(ids)
    out = {}
    for i in ids:
        s = stats.get(i, {})
        p = prof.get(i, {})
        out[str(i)] = dict(
            id=i, name=p.get("name") or names.get(i, {}).get("name"), **{k: v for k, v in p.items() if k != "name"},
            group=s.get("group_at_tabling") or (p.get("groups") or [None])[-1] or names.get(i, {}).get("iw_group"),
            rapporteur=(p.get("name") or names.get(i, {}).get("name")) in RAPPORTEURS,
            tabled=s.get("tabled", 0), lead=s.get("lead", 0), survived=s.get("survived", 0), law=s.get("law", 0),
            ai_committees=s.get("committees", []),
            echoed_orgs=[dict(org=e["org"], name=e["name"], type=e["type"], amendments=e["amendments"], law=e["law"])
                         for e in echoes if e["id"] == i][:25],
            meetings=[dict(org=m["org"], name=m["name"], date=m["date"], title=m["title"], role=m["role"], ai=m["ai"])
                      for m in meets if m["id"] == i][:60])
    return out


# ---------------------------------------------------------------- lobbies
def lobbies() -> dict:
    base = {r["org_id"]: r for r in graph.run("""
        MATCH (o:Organisation)
        RETURN o.org_id AS org_id, o.name AS name, o.user_type AS type, o.country AS country, o.company_size AS size,
               o.register_name AS register_name, o.match_method AS match_method, o.in_register_now AS in_register,
               o.lobbying_cost_eur AS cost, o.costs_is_range AS cost_range, o.fte AS fte, o.ep_passes_all AS ep_passes,
               o.ec_meetings_all AS ec_meetings_all, o.ec_meetings_vdl1 AS ec_meetings, o.mep_meetings_all AS mep_meetings_register,
               o.reg_date AS reg_date, o.register_category AS category, o.interest_represented AS interest,
               o.fields_of_interest AS fields, o.lobbyfacts_url AS lobbyfacts_url, o.head_office AS head_office,
               coalesce(o.influence_b, 0) AS influence, o.coalition AS coalition, o.tr_id AS tr_id""")}
    comments = graph.run("""
        MATCH (o:Organisation)-[:SUBMITTED]->(c:Comment)
        RETURN o.org_id AS org, c.feedback_id AS id, c.track AS track, c.date AS date, c.url AS url, c.n_words AS words,
               c.has_attachment AS attachment ORDER BY c.date""")
    echoed = graph.run(f"""
        MATCH (o:Organisation)-[:SUBMITTED]->(:Comment {{track:'B'}})<-[:PART_OF]-(c:Chunk)-[e:ECHOED_IN]->(a:Amendment)
        WHERE {ECHO}
        WITH o, a, max(e.score) AS score, collect(e)[0] AS e1, count(c) AS chunks, max(CASE WHEN e.verbatim THEN 1 ELSE 0 END) AS verbatim
        OPTIONAL MATCH (m:MEP)-[:TABLED {{is_lead_author:true}}]->(a)
        RETURN o.org_id AS org, a.am_id AS am, a.location AS location, a.committee AS committee, m.mep_id AS lead_mep,
               m.name AS lead_mep_name, a.survived AS survived, a.reached_law AS law, a.p_survived AS p_survived,
               a.p_reached_law AS p_law, score, e1.tier AS tier, e1.llm_relation AS relation, e1.llm_direction AS direction,
               chunks, verbatim = 1 AS verbatim
        ORDER BY law DESC, survived DESC, score DESC""")
    carriers = graph.run(f"""
        MATCH (o:Organisation)-[:SUBMITTED]->(:Comment)<-[:PART_OF]-(:Chunk)-[e:ECHOED_IN]->(a:Amendment)<-[t:TABLED]-(m:MEP)
        WHERE {ECHO}
        WITH DISTINCT o, m, a, t
        RETURN o.org_id AS org, m.mep_id AS mep, m.name AS name, t.group AS grp, count(a) AS amendments,
               sum(CASE WHEN a.reached_law THEN 1 ELSE 0 END) AS law ORDER BY amendments DESC""")
    meetings = graph.run("""
        MATCH (o:Organisation)-[r:MET_WITH]->(m:MEP)
        RETURN o.org_id AS org, m.mep_id AS mep, m.name AS name, coalesce(m.iw_group, '') AS grp, r.date AS date,
               r.title AS title, r.mep_role AS role, r.ai_related AS ai ORDER BY r.date""")
    positions = graph.run("""
        MATCH (o:Organisation)-[r:TOOK_POSITION]->(i:Issue)
        RETURN o.org_id AS org, i.issue_id AS issue, i.label AS label, r.stance AS stance, r.quote AS quote,
               i.proposal_choice AS proposal_choice, r.aligned AS aligned""")
    track_a = graph.run(f"""
        MATCH (o:Organisation)-[:SUBMITTED]->(:Comment {{track:'A'}})<-[:PART_OF]-(c:Chunk)-[e:ECHOED_IN]->(p:Provision)
        WHERE {ECHO}
        OPTIONAL MATCH (p)-[b:BECAME]->(l:LegalUnit)
        RETURN o.org_id AS org, p.unit_id AS unit, max(e.score) AS score, collect(e.llm_relation)[0] AS relation,
               count(b) > 0 AS in_law, collect(l.law_unit_id)[0] AS law_unit ORDER BY score DESC""")
    similar = graph.run("""
        MATCH (o1:Organisation)-[:SUBMITTED]->(:Comment)<-[:PART_OF]-(:Chunk)-[:SIMILAR_TO]-(:Chunk)-[:PART_OF]->(:Comment)<-[:SUBMITTED]-(o2:Organisation)
        WHERE o1 <> o2 RETURN o1.org_id AS org, o2.org_id AS other, o2.name AS name, count(*) AS chunks ORDER BY chunks DESC""")
    out = {}
    for oid, b in base.items():
        ech = [e for e in echoed if e["org"] == oid]
        pos = [p for p in positions if p["org"] == oid]
        al = [p["aligned"] for p in pos if p["aligned"] is not None]
        ta = [t for t in track_a if t["org"] == oid]
        out[oid] = J(dict(
            **{**b, "fields": [f.strip() for f in (b["fields"] or "").split(",") if f.strip()]},
            comments=[c for c in comments if c["org"] == oid],
            echoed=ech[:60], n_echoed=len(ech), n_survived=sum(1 for e in ech if e["survived"]),
            n_law=sum(1 for e in ech if e["law"]), n_verbatim=sum(1 for e in ech if e["verbatim"]),
            expected_law=float(sum(e["p_law"] or 0 for e in ech)) if ech else None,
            carriers=[c for c in carriers if c["org"] == oid][:20],
            meetings=[m for m in meetings if m["org"] == oid],
            positions=pos, aligned_share=(sum(al) / len(al)) if al else None, n_positions=len(pos),
            track_a=ta[:20], track_a_in_law=sum(1 for t in ta if t["in_law"]),
            similar=[s for s in similar if s["org"] == oid][:8]))
    return out


# ---------------------------------------------------------------- articles: similar comments
K_STORE = 40          # most similar comments kept per article and track
DUP_COS = 0.96        # chunk-chunk cosine above which two comments are drawn as near-duplicates
SNIP = 700


def article_label(uid: str) -> str:
    if uid.startswith("Art"):
        return "Article " + uid[3:]
    if uid.startswith("Annex"):
        return "Annex " + uid[5:]
    if uid.startswith("Rec"):
        return "Recital " + uid[3:]
    return uid


ROMAN = dict(I=1, V=5, X=10, L=50)


def _unit_order(uid: str) -> tuple:
    """Articles, then annexes, then recitals, each in numeric order (Annex numbers are roman)."""
    for k, pre in enumerate(("Art", "Annex", "Rec")):
        if uid.startswith(pre):
            s = uid[len(pre):]
            if pre == "Annex":
                vals = [ROMAN.get(c, 0) for c in s]
                n = sum(-v if i + 1 < len(vals) and v < vals[i + 1] else v for i, v in enumerate(vals))
            else:
                n = int("".join(c for c in s if c.isdigit()) or 0)
            return k, n, s
    return 9, 0, uid


def articles() -> tuple[list[dict], dict, dict]:
    """For every article / recital / annex: the comments whose paragraphs are closest to its text.
    Track A (2020 comments): cosine to the closest proposal provision under the article.
    Track B (2021 comments): cosine to the closest committee amendment (inserted words) on the article.
    Returns (articles, chunks, targets)."""
    from .units import top

    F = config.FEATURES
    prov = pd.read_parquet(config.CACHE / "s02_proposal_units.parquet").set_index("unit_id")
    props = pd.read_parquet(config.CACHE / "s04_amendment_props.parquet").set_index("am_id")
    meta = pd.DataFrame(graph.run("""
        MATCH (o:Organisation)-[:SUBMITTED]->(cm:Comment)<-[:PART_OF]-(c:Chunk)
        RETURN c.chunk_id AS cid, o.org_id AS org, o.name AS org_name, o.user_type AS type, cm.track AS track,
               cm.url AS url, cm.date AS date""")).set_index("cid")
    judged = {}
    for t in "AB":
        p = config.CACHE / f"s09_judged_{t}.parquet"
        if p.exists():
            j = pd.read_parquet(p)
            for r in j.itertuples():
                judged[(r.chunk_id, r.target_id)] = (r.llm_relation, r.tier, bool(r.hidden) if r.hidden == r.hidden else False)
    data = {}
    for t in "AB":
        ch = pd.read_parquet(F / f"{t}_chunks.parquet")
        tg = pd.read_parquet(F / f"{t}_targets.parquet")
        art = tg["id"].map(lambda u: top(u)) if t == "A" else tg.target_unit_id.map(lambda u: top(u) if isinstance(u, str) else None)
        data[t] = dict(ch=ch, E=np.load(F / f"{t}_chunks_emb.npy"), tg=tg, G=np.load(F / f"{t}_targets_emb.npy"), art=art.to_numpy())
    am_all = pd.read_parquet(config.CACHE / "s03_amendments.parquet")
    am_art = am_all.target_unit_id.map(lambda u: top(u) if isinstance(u, str) else None)
    ids = sorted({a for d in data.values() for a in d["art"] if isinstance(a, str)}, key=_unit_order)
    chunks, targets, out = {}, {}, []
    for X in ids:
        entry = dict(id=X, kind="recital" if X.startswith("Rec") else "annex" if X.startswith("Annex") else "article",
                     label=article_label(X), title=(prov.title.get(X) if X in prov.index else None),
                     text=(prov.full_text.get(X) or "")[:900] if X in prov.index else "", A=[], B=[], dups=[])
        vecs, cids = [], []
        for t in "AB":
            d = data[t]
            idx = np.flatnonzero(d["art"] == X)
            if not len(idx):
                continue
            S = d["E"] @ d["G"][idx].T
            best, arg = S.max(1), S.argmax(1)
            for i in np.argsort(-best)[:K_STORE]:
                cid, tid = d["ch"].id.iat[i], d["tg"]["id"].iat[idx[arg[i]]]
                rel = judged.get((cid, tid))
                entry[t].append([cid, round(float(best[i]), 4), tid, rel[0] if rel and not rel[2] else None, rel[1] if rel and not rel[2] else None])
                if cid not in chunks and cid in meta.index:
                    m = meta.loc[cid]
                    chunks[cid] = dict(org=m.org, name=m.org_name, type=m.type, track=m.track, url=m.url, date=m.date,
                                       text=d["ch"].text.iat[i][:SNIP])
                if tid not in targets:
                    row = d["tg"].iloc[idx[arg[i]]]
                    targets[tid] = dict(loc=(row.get("location") if t == "B" else tid), text=str(row.text)[:SNIP])
                vecs.append(d["E"][i])
                cids.append(cid)
        if len(cids) > 1:
            V = np.stack(vecs)
            C = V @ V.T
            ii, jj = np.where(np.triu(C, 1) >= DUP_COS)
            pairs = sorted(((float(C[a, b]), cids[a], cids[b]) for a, b in zip(ii, jj) if cids[a] != cids[b]), reverse=True)[:150]
            entry["dups"] = [[a, b, round(c, 3)] for c, a, b in pairs]
        sel = am_art == X
        entry["n_am"] = int(sel.sum())
        entry["n_survived"] = int(props.loc[am_all.am_id[sel]].survived.sum()) if sel.any() else 0
        entry["n_law"] = int(props.loc[am_all.am_id[sel]].reached_law.sum()) if sel.any() else 0
        entry["n_echo"] = len({(c, tt) for t in "AB" for c, _, tt, rel, tier in entry[t] if tier in ("T1", "T2")})
        out.append(entry)
    return out, chunks, targets


# ---------------------------------------------------------------- stories
def stories() -> list[dict]:
    rows = graph.run(f"""
        MATCH (o:Organisation)-[:SUBMITTED]->(cm:Comment {{track:'B'}})<-[:PART_OF]-(c:Chunk)-[e:ECHOED_IN]->(a:Amendment)
        WHERE {ECHO}
        WITH o, cm, c, e, a ORDER BY e.score DESC
        WITH o, a, collect({{cm: cm, c: c, e: e}})[0] AS best
        OPTIONAL MATCH (a)-[s:SURVIVED_AS]->(x:AdoptedAmendment)
        OPTIONAL MATCH (x)-[b:BECAME]->(l:LegalUnit)
        OPTIONAL MATCH (a)-[:AMENDS]->(p:Provision)
        RETURN o.org_id AS org, o.name AS org_name, o.user_type AS type, best.cm.date AS comment_date, best.cm.url AS url,
               best.c.chunk_id AS chunk_id, best.c.text AS chunk, best.e.score AS score, best.e.tier AS tier,
               best.e.verbatim AS verbatim, best.e.longest_run AS run, best.e.run_text AS run_text,
               best.e.llm_relation AS relation, best.e.llm_direction AS direction, best.e.overlap_quote AS quote,
               best.e.carrier_met AS carrier_met,
               a.am_id AS am, a.location AS location, a.committee AS committee, a.date AS am_date, a.old_text AS old_text,
               a.new_text AS new_text, a.added_text AS added, a.src AS am_src, a.survived AS survived,
               a.reached_law AS law, a.survival_score AS survival_score, a.p_survived AS p_survived,
               a.p_reached_law AS p_law, a.p_survived_explain AS x_survived, a.p_reached_law_explain AS x_law,
               [(m:MEP)-[t:TABLED]->(a) | {{id: m.mep_id, name: m.name, group: t.group, lead: t.is_lead_author}}] AS meps,
               x.adopted_id AS adopted, x.text AS adopted_text, x.date AS adopted_date, s.score AS s_score,
               l.law_unit_id AS law_unit, coalesce(l.text_as_adopted, l.text) AS law_text, b.added_kept AS kept,
               p.unit_id AS provision, p.text AS provision_text""")
    df = pd.DataFrame(rows)
    df = df.sort_values(["law", "survived", "verbatim", "score"], ascending=False).drop_duplicates(["org", "am"])
    df = df.drop_duplicates(["am", "law_unit", "org"]).head(400)
    for c in ("x_survived", "x_law"):
        df[c] = df[c].map(lambda s: json.loads(s) if isinstance(s, str) else [])
    return J(df.to_dict("records"))


def featured(st: list[dict]) -> int:
    """The default story: reached the law, verbatim if possible, judged 'implements', highest score."""
    best, key = 0, None
    for i, s in enumerate(st):
        k = (bool(s.get("law")), s.get("relation") == "implements", bool(s.get("verbatim")), s.get("score") or 0)
        if key is None or k > key:
            best, key = i, k
    return best


def influence() -> dict:
    metrics = json.loads((R / "reach_model_metrics.json").read_text())
    coef = pd.read_csv(R / "reach_model.csv")
    became = graph.run("""
        MATCH (p:Provision) WHERE p.text IS NOT NULL AND size(split(p.text, ' ')) >= 3
        OPTIONAL MATCH (p)-[b:BECAME]->()
        RETURN count(DISTINCT p) AS provisions, count(DISTINCT CASE WHEN b IS NOT NULL THEN p END) AS in_law""")[0]
    echoed_a = graph.run(f"""
        MATCH (:Chunk)-[e:ECHOED_IN]->(p:Provision) WHERE {ECHO}
        WITH DISTINCT p OPTIONAL MATCH (p)-[b:BECAME]->()
        RETURN count(DISTINCT p) AS provisions, count(DISTINCT CASE WHEN b IS NOT NULL THEN p END) AS in_law""")[0]
    issues = graph.run("""
        MATCH (i:Issue) OPTIONAL MATCH (o:Organisation)-[r:TOOK_POSITION]->(i)
        RETURN i.issue_id AS issue, i.label AS label, i.proposal_choice AS choice, i.proposal_quote AS quote,
               i.article_ref AS article, i.agreement AS agreement, count(r) AS positions,
               avg(CASE WHEN r.aligned THEN 1.0 WHEN r.aligned = false THEN 0.0 END) AS aligned,
               [s IN collect(r.stance) WHERE s IS NOT NULL] AS stances""")
    for i in issues:
        s = pd.Series(i.pop("stances"))
        i["stance_counts"] = s.value_counts().to_dict() if len(s) else {}
    return J(dict(metrics=metrics, coef=coef.to_dict("records"), became=became, echoed_a=echoed_a, issues=issues,
                  alignment=csvr("track_a_alignment"), funnel=csvr("02_reach_funnel"), access=csvr("access_vs_echo"),
                  money=csvr("money_vs_influence")))


def main(track: str | None = None) -> None:
    lob = lobbies()
    lobby_meps = {c["mep"] for o in lob.values() for c in o["carriers"]} | {m["mep"] for o in lob.values() for m in o["meetings"]}
    mp = meps({int(x) for x in lobby_meps if x is not None})
    st = stories()
    arts, art_chunks, art_targets = articles()
    th = {}
    for f in ("s04_thresholds.json", "s08_thresholds.json"):
        if (config.DATA / f).exists():
            th[f[:3]] = json.loads((config.DATA / f).read_text())
            
    eval_metrics = {}
    if (config.RESULTS / "eval.csv").exists():
        eval_metrics = pd.read_csv(config.RESULTS / "eval.csv").to_dict(orient="records")[0]

    data = J(dict(acts=ACTS, lobbies=lob, meps=mp, stories=st, featured=featured(st), influence=influence(),
                articles=arts, art_chunks=art_chunks, art_targets=art_targets, art_dup_cos=DUP_COS,
                counts=graph.counts(), thresholds=th, eval=eval_metrics,
                models=dict(judge=config.LLM_MODEL, second=config.LLM_MODEL_SECOND, embed=config.EMBED_MODEL)))
    import plotly

    js = (Path(plotly.__file__).parent / "package_data" / "plotly.min.js").read_text()
    html = TEMPLATE.read_text().replace("__PLOTLYJS__", js).replace(
        "__DATA__", json.dumps(data, ensure_ascii=False, allow_nan=False).replace("</", "<\\/"))
    (R / "demo.html").write_text(html)
    print(f"   demo.html {len(html) / 1e6:.1f} MB: {len(lob)} lobbies, {len(mp)} MEPs, {len(st)} stories, {len(arts)} articles "
          f"(featured: {st[data['featured']]['org_name']} -> {st[data['featured']]['location']})")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
