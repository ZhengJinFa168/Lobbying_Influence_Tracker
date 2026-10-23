"""Paths, identifiers, thresholds and model names shared by every stage."""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from dotenv import dotenv_values, load_dotenv

ROOT = Path(__file__).resolve().parent.parent
_CALLER_ENV = set(os.environ)  # variables set by the caller win over every .env file
load_dotenv(ROOT / ".env")

# --- procedure -------------------------------------------------------------
# One file per legislative procedure: data_sources/procedures/<id>.yaml (format in ai_act.yaml).
# Pick it with `python -m pipeline.run --procedure <id>` or PROCEDURE_ID in the environment; ai_act is the default.
# A procedure other than the default needs its own Neo4j: NEO4J_URI and NEO4J_PASSWORD in .env.<id> (gitignored)
# or the caller's environment; NEO4J_* from .env (the default procedure's database) are never used for it.
PROCEDURES_DIR = ROOT / "data_sources" / "procedures"
DEFAULT_PROCEDURE = "ai_act"
PROCEDURE_ID = os.getenv("PROCEDURE_ID") or DEFAULT_PROCEDURE
_REQUIRED = ("id", "procedure", "null_procedure", "consultation", "data_dir")


def _load_procedure(pid: str) -> dict:
    p = PROCEDURES_DIR / f"{pid}.yaml"
    if not re.fullmatch(r"[a-z0-9_]+", pid) or not p.is_file():
        known = ", ".join(sorted(f.stem for f in PROCEDURES_DIR.glob("*.yaml")))
        raise SystemExit(f"unknown procedure {pid!r}: expected data_sources/procedures/<id>.yaml, one of: {known}")
    proc = yaml.safe_load(p.read_text(encoding="utf-8"))
    missing = [k for k in _REQUIRED if not isinstance(proc, dict) or proc.get(k) is None]
    if missing:
        raise SystemExit(f"{p.name}: missing {', '.join(missing)}")
    if proc["id"] != pid:
        raise SystemExit(f"{p.name}: id is {proc['id']!r}, expected {pid!r}")
    if not isinstance(proc["consultation"], dict):
        raise SystemExit(f"{p.name}: consultation must be a mapping of tracks")
    for track, c in proc["consultation"].items():
        if track == "initiative":
            continue
        pub = c.get("publication") if isinstance(c, dict) else None
        if not (c is None or isinstance(c, dict)) or not (pub is None or type(pub) is int or str(pub).isdigit()):
            raise SystemExit(f"{p.name}: consultation.{track} needs a numeric publication (or null)")
    data_root = (ROOT / "data").resolve()
    target = (ROOT / proc["data_dir"]).resolve()
    if target != (data_root if pid == DEFAULT_PROCEDURE else data_root / pid):
        raise SystemExit(f"{p.name}: data_dir must be data/{'' if pid == DEFAULT_PROCEDURE else pid}")
    return proc


PROC = _load_procedure(PROCEDURE_ID)   # the whole procedure config; stages read their fields from here
PROCEDURE = PROC["procedure"]
NULL_PROCEDURE = PROC["null_procedure"]  # unrelated file whose committee amendments set the S08 null distribution
PUB_IDS = {t: int(c["publication"]) for t, c in PROC["consultation"].items()
           if t != "initiative" and isinstance(c, dict) and c.get("publication") is not None}
TRACK_OF_PUB = {pub: t for t, pub in PUB_IDS.items()}
if PROCEDURE_ID != DEFAULT_PROCEDURE:
    for _k in [k for k in os.environ if k.startswith("NEO4J_") and k not in _CALLER_ENV]:
        del os.environ[_k]  # came from .env, i.e. the default procedure's database
for _k, _v in dotenv_values(ROOT / f".env.{PROCEDURE_ID}").items():
    if _k not in _CALLER_ENV and _v is not None:
        os.environ[_k] = _v

# --- paths -----------------------------------------------------------------
SOURCES_YAML = ROOT / "data_sources" / "sources.yaml"
DATA = ROOT / PROC["data_dir"]  # per procedure: data/ for the AI Act (legacy), data/<id>/ otherwise
CACHE = DATA / "cache"          # parquet tables written by loaders (S01-S04, S06)
FEATURES = DATA / "features"    # embeddings / tfidf caches (S05)
RESULTS = DATA / "results"      # analysis CSVs (S10), graph.json, dashboard
LLM_CACHE = ROOT / "data" / "llm_cache.sqlite"   # shared by all procedures: keyed by prompt, so answers are reused
LLM_COST_LOG = ROOT / "data" / "llm_costs.csv"
NEO4J_DIR = ROOT / "neo4j"
QUERIES = NEO4J_DIR / "queries"
EVAL = ROOT / "eval"
for _p in (DATA, CACHE, FEATURES, RESULTS):
    _p.mkdir(parents=True, exist_ok=True)

# --- neo4j -----------------------------------------------------------------
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
BATCH = 1000


def _endpoint(uri: str) -> tuple[str, int]:
    u = urlsplit(uri.strip())
    host = (u.hostname or "").lower()
    return ("loopback" if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0") else host), u.port or 7687


if PROCEDURE_ID != DEFAULT_PROCEDURE:
    _default_uri = dotenv_values(ROOT / ".env").get("NEO4J_URI") or "bolt://localhost:7687"
    _fix = f"set NEO4J_URI and NEO4J_PASSWORD for its own instance in .env.{PROCEDURE_ID}"
    if not os.getenv("NEO4J_URI") or not os.getenv("NEO4J_PASSWORD"):
        raise SystemExit(f"procedure {PROCEDURE_ID} has no Neo4j of its own: {_fix}")
    if _endpoint(NEO4J_URI) == _endpoint(_default_uri):
        raise SystemExit(f"procedure {PROCEDURE_ID} would use the {DEFAULT_PROCEDURE} Neo4j at {NEO4J_URI}: {_fix}")

# --- LLM (OpenRouter) ------------------------------------------------------
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek/deepseek-v4-flash")
LLM_MODEL_SECOND = os.getenv("LLM_MODEL_SECOND", "google/gemini-2.5-flash-lite")
LLM_MODEL_HARD = os.getenv("LLM_MODEL_HARD", "deepseek/deepseek-v4-pro")
LLM_CONCURRENCY = int(os.getenv("LLM_CONCURRENCY", "12"))
LLM_MAX_PAIRS_PER_TRACK = 2000
JUDGE_MAX_TOKENS = 300
STANCE_MAX_TOKENS = 800
LLM_SEED = 42

# --- embeddings / matching -------------------------------------------------
EMBED_MODEL = "intfloat/multilingual-e5-base"
CHUNK_MIN_WORDS, CHUNK_MAX_WORDS = 80, 150
STOPLIST_N = 6            # proposal word n-gram stoplist
VERBATIM_RUN = 12         # longest identical run (words) => verbatim
TOPK_EMBED = 10
SCORE_WEIGHTS = {"s_embed": 0.5, "s_tfidf": 0.3, "s_ngram": 0.2}
SIMILAR_TO_COS = 0.9
NULL_PERCENTILE = 99
TIER_WEIGHT = {"T1": 3.0, "T2": 2.0, "T3": 1.0}

# --- run id ----------------------------------------------------------------
RUN_ID = os.getenv("RUN_ID") or datetime.utcnow().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:4]
