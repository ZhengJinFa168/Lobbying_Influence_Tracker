"""Text-matching helpers shared by S05, S07 and S08: word tokens and n-grams, the proposal 6-gram stoplist,
masked token lists (stoplisted spans and common quotes become gaps), the longest identical run, 3-gram overlap and
the combined z-scored match score. Moved verbatim out of s05_features and s07_match so stages do not import each other.
"""
from __future__ import annotations

import pickle
import re
from difflib import SequenceMatcher

import numpy as np
import pandas as pd
import scipy.sparse as sp

from . import config
from .textutil import ascii_fold

F = config.FEATURES
N = config.STOPLIST_N
NGRAM_SMOOTH = 5         # added to the 3-gram denominator
COMMON_N = 12            # length of a common quote (S07 common_quotes)


def tokens(s) -> list[str]:
    s = ascii_fold(s if isinstance(s, str) else "").lower()
    return re.findall(r"[a-z0-9]+", s)


def ngrams(toks: list[str], n: int = N) -> list[tuple]:
    return [tuple(toks[i : i + n]) for i in range(len(toks) - n + 1)]


def stoplist(track: str) -> set[tuple]:
    if track == "A":
        return set()
    return pickle.load(open(F / "stoplist_6grams.pkl", "rb"))


def ngram_tokens(text, stop: set[tuple]) -> list[str | None]:
    """Tokens with every position covered by a stoplisted 6-gram replaced by None."""
    toks = tokens(text)
    masked = list(toks)
    for i, g in enumerate(ngrams(toks)):
        if g in stop:
            for k in range(i, i + N):
                masked[k] = None
    return masked


def load(track: str, kind: str):
    df = pd.read_parquet(F / f"{track}_{kind}.parquet")
    return df, np.load(F / f"{track}_{kind}_emb.npy"), sp.load_npz(F / f"{track}_{kind}_tfidf.npz")


class _Gap:  # a masked (stoplisted) position: never equal to anything, so runs cannot cross it
    def __eq__(self, other):
        return False

    def __hash__(self):
        return id(self)


def masked(text, stop, common: set[tuple] = frozenset()) -> list:
    toks = ngram_tokens(text, stop)
    if common:
        raw = tokens(text)
        for i, g in enumerate(ngrams(raw, COMMON_N)):
            if g in common:
                for k in range(i, i + COMMON_N):
                    toks[k] = None
    return [t if t is not None else _Gap() for t in toks]


def longest_run(a: list, b: list) -> tuple[int, str]:
    if not a or not b:
        return 0, ""
    m = SequenceMatcher(None, a, b, autojunk=False).find_longest_match(0, len(a), 0, len(b))
    return m.size, " ".join(str(x) for x in a[m.a : m.a + m.size])


def tri(tokens: list) -> set:
    return {g for g in ngrams([t if isinstance(t, str) else None for t in tokens], 3) if None not in g}


def pair_features(chunk_tok: list, target_tok: list, target_tri: set) -> dict:
    run, run_text = longest_run(chunk_tok, target_tok)
    # smoothed share: a target with 2 free 3-grams that both occur is not "100% shared"
    s_ngram = len(target_tri & tri(chunk_tok)) / (len(target_tri) + NGRAM_SMOOTH)
    return dict(s_ngram=s_ngram, longest_run=run, run_text=run_text if run >= 5 else None)


def combine(df: pd.DataFrame, st: dict) -> pd.Series:
    w = config.SCORE_WEIGHTS
    return (w["s_embed"] * (df.s_embed - st["embed_mean"]) / st["embed_std"]
            + w["s_tfidf"] * (df.s_tfidf - st["tfidf_mean"]) / st["tfidf_std"]
            + w["s_ngram"] * (df.s_ngram - st["ngram_mean"]) / st["ngram_std"])
