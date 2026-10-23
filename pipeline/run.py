"""Pipeline runner.

    python -m pipeline.run                      # every implemented stage, both tracks
    python -m pipeline.run --from s03 --track B
    python -m pipeline.run --only s00
    python -m pipeline.run --procedure dsa      # data_sources/procedures/dsa.yaml (default: ai_act)

Each stage module exposes main(track: str | None) (S00 ignores track). Stages that are not
implemented yet are skipped with a note, so the runner works while the plan is built step by step.
For a procedure other than ai_act, only S00 and stages that set PROCEDURE_AWARE = True run: the others still
hard-code AI Act inputs and shared output paths, and would overwrite AI Act files.
"""
from __future__ import annotations

import argparse
import importlib
import logging
import os
import sys
import time

STAGES = [
    "s00_check", "s01_feedback", "s02_legal_texts", "s03_amendments", "s04_survival", "s05_features",
    "s06_orgs", "s06b_meetings", "s07_match", "s08_calibrate", "s09_judge_and_stance", "s10_analyse", "s10b_reach_model",
    "s11_export_dashboard", "s11b_demo", "s12_eval",
]


def _select(frm: str | None, only: str | None) -> list[str]:
    def idx(prefix):
        for i, s in enumerate(STAGES):
            if s.split("_")[0] == prefix.lower() or s == prefix:
                return i
        raise SystemExit(f"unknown stage {prefix}")

    if only:
        return [STAGES[idx(o)] for o in only.split(",")]
    return STAGES[idx(frm):] if frm else STAGES


def _procedure_aware(name: str) -> bool:
    try:
        return bool(getattr(importlib.import_module(f"pipeline.{name}"), "PROCEDURE_AWARE", False))
    except ModuleNotFoundError as e:
        if e.name == f"pipeline.{name}":
            return True  # not implemented: the run loop skips it with a note
        raise


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm")
    ap.add_argument("--only")
    ap.add_argument("--track", choices=["A", "B"])
    ap.add_argument("--procedure", help="procedure config id in data_sources/procedures/ (default: $PROCEDURE_ID or ai_act)")
    a = ap.parse_args()
    # config reads PROCEDURE_ID once, at import, so set it before anything imports config
    if a.procedure is not None:
        if not a.procedure:
            raise SystemExit("--procedure needs an id")
        loaded = sys.modules.get("pipeline.config")
        if loaded is not None and loaded.PROCEDURE_ID != a.procedure:
            raise SystemExit(f"pipeline.config was already loaded for {loaded.PROCEDURE_ID!r}, not {a.procedure!r}")
        os.environ["PROCEDURE_ID"] = a.procedure
    from . import config

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(f"run_id={config.RUN_ID} procedure={config.PROCEDURE_ID} ({config.PROCEDURE}) track={a.track or 'A+B'}")
    selected = _select(a.frm, a.only)
    if config.PROCEDURE_ID != config.DEFAULT_PROCEDURE:
        # a stage opts in with a module-level PROCEDURE_AWARE = True once it reads everything from config.PROC
        blocked = [n for n in selected if n != "s00_check" and not _procedure_aware(n)]
        if blocked:
            raise SystemExit(f"not adapted to procedure {config.PROCEDURE_ID!r} yet (no PROCEDURE_AWARE): {', '.join(blocked)}")
    for name in selected:
        try:
            mod = importlib.import_module(f"pipeline.{name}")
        except ModuleNotFoundError as e:
            if e.name == f"pipeline.{name}":
                print(f"-- {name}: not implemented yet, skipped")
                continue
            raise
        t = time.time()
        print(f"== {name}")
        mod.main() if name == "s00_check" else mod.main(track=a.track)
        print(f"   {name} done in {time.time() - t:.1f}s")


if __name__ == "__main__":
    main()
