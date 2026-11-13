"""Pure matching rules (generated): integer scores, deterministic order, a batch solver. No database.

score parts (all integers 0..1000):  distance = 1000 - 1000*d // max_distance_m   (d = haversine metres)
                                     load     = 1000 - 1000*min(load, max_load) // max_load
                                     rating   = rating_milli // 5            (rating_milli 0..5000)
score = w_distance * distance + w_load * load + w_rating * rating, then `adjust_score`.
Rules: a candidate farther than max_distance_m, or with load >= max_load, is not eligible.
Order everywhere: score descending, distance ascending, candidate id ascending: no two orders are ever tied."""

import typing as _t
from dataclasses import dataclass
from functools import cache

from app.operations.geomath import haversine_m

Point = tuple[int, int]


@dataclass(frozen=True)
class Candidate:
    id: str
    lat_micro: int
    lng_micro: int
    load: int = 0
    rating_milli: int = 0


@dataclass(frozen=True)
class Weights:
    distance: int
    load: int
    rating: int


@dataclass(frozen=True)
class Ranked:
    candidate_id: str
    score: int
    distance_m: int
    parts: tuple[int, int, int]  # distance, load, rating


def adjust_score(candidate: Candidate, base_score: int) -> int:
    """THE SCORE HOOK. Return the final score for `candidate` (an integer). The default keeps the weighted score;
    a custom extension may add or subtract business rules here (skills, zones, priorities). Must stay pure and
    deterministic: the same inputs must always give the same integer."""
    return base_score


def score_parts(distance_m: int, load: int, rating_milli: int, max_distance_m: int, max_load: int) -> tuple[int, int, int]:
    return (
        1000 - 1000 * distance_m // max_distance_m,
        1000 - 1000 * min(load, max_load) // max_load,
        max(0, min(5000, rating_milli)) // 5,
    )


def evaluate(point: Point, cand: Candidate, weights: Weights, max_distance_m: int, max_load: int) -> Ranked | str:
    """A Ranked, or the reason the candidate is excluded: "too_far" or "overloaded"."""
    distance = haversine_m(point[0], point[1], cand.lat_micro, cand.lng_micro)
    if distance > max_distance_m:
        return "too_far"
    if cand.load >= max_load:
        return "overloaded"
    parts = score_parts(distance, cand.load, cand.rating_milli, max_distance_m, max_load)
    base = weights.distance * parts[0] + weights.load * parts[1] + weights.rating * parts[2]
    return Ranked(cand.id, adjust_score(cand, base), distance, parts)


def order_key(r: Ranked) -> tuple[int, int, str]:
    return (-r.score, r.distance_m, r.candidate_id)


def rank(
    point: Point, candidates: _t.Sequence[Candidate], weights: Weights, max_distance_m: int, max_load: int,
    skip: _t.Collection[str] = (),
) -> tuple[list[Ranked], list[tuple[str, str]]]:
    ranked: list[Ranked] = []
    excluded: list[tuple[str, str]] = []
    for cand in candidates:
        if cand.id in skip:
            excluded.append((cand.id, "previously_declined"))
            continue
        result = evaluate(point, cand, weights, max_distance_m, max_load)
        if isinstance(result, str):
            excluded.append((cand.id, result))
        else:
            ranked.append(result)
    ranked.sort(key=order_key)
    return ranked, sorted(excluded)


# --- batch solver ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Pair:
    request_ref: str
    candidate_id: str
    score: int
    distance_m: int


def solve_batch(
    requests: _t.Sequence[tuple[str, Point]], candidates: _t.Sequence[Candidate], weights: Weights,
    max_distance_m: int, max_load: int, skip: _t.Mapping[str, _t.Collection[str]] | None = None,
    exact_requests: int = 8, exact_candidates: int = 12,
) -> tuple[list[Pair], list[str], str]:
    """(pairs, unassigned request refs, "optimal" | "greedy"). Each candidate takes at most one request. Maximises
    (requests served, total score, then minimal total distance); exact for small inputs, greedy (best pair first)
    otherwise. Deterministic: inputs are sorted by id / ref first and ties follow the fixed order above."""
    skip = skip or {}
    reqs = sorted(requests, key=lambda r: r[0])
    cands = sorted(candidates, key=lambda c: c.id)
    options: list[list[tuple[Ranked, int]]] = []  # per request: eligible (ranked, candidate index), best first
    for ref, point in reqs:
        found = []
        for index, cand in enumerate(cands):
            if cand.id in skip.get(ref, ()):
                continue
            result = evaluate(point, cand, weights, max_distance_m, max_load)
            if not isinstance(result, str):
                found.append((result, index))
        found.sort(key=lambda f: order_key(f[0]))
        options.append(found)
    if len(reqs) <= exact_requests and len(cands) <= exact_candidates:
        chosen = _exact(options)
        solver = "optimal"
    else:
        chosen = _greedy(reqs, options)
        solver = "greedy"
    pairs = [
        Pair(reqs[i][0], r.candidate_id, r.score, r.distance_m) for i, pick in sorted(chosen.items()) for r in [pick[0]]
    ]
    unassigned = [ref for i, (ref, _p) in enumerate(reqs) if i not in chosen]
    return pairs, unassigned, solver


def _greedy(reqs: _t.Sequence[tuple[str, Point]], options: list[list[tuple[Ranked, int]]]) -> dict[int, tuple[Ranked, int]]:
    flat = sorted(
        ((i, r, c) for i, opts in enumerate(options) for r, c in opts),
        key=lambda t: (-t[1].score, t[1].distance_m, reqs[t[0]][0], t[1].candidate_id),
    )
    taken_c: set[int] = set()
    chosen: dict[int, tuple[Ranked, int]] = {}
    for i, r, c in flat:
        if i not in chosen and c not in taken_c:
            chosen[i] = (r, c)
            taken_c.add(c)
    return chosen


def _exact(options: list[list[tuple[Ranked, int]]]) -> dict[int, tuple[Ranked, int]]:
    @cache
    def best(i: int, used: int) -> tuple[int, int, int]:
        """Best (served, total score, -total distance) for requests i.. given the used-candidate mask."""
        if i == len(options):
            return (0, 0, 0)
        top = best(i + 1, used)  # leave request i unassigned
        for r, c in options[i]:
            if used >> c & 1:
                continue
            a, b, d = best(i + 1, used | 1 << c)
            top = max(top, (a + 1, b + r.score, d - r.distance_m))
        return top

    chosen: dict[int, tuple[Ranked, int]] = {}
    used = 0
    for i, opts in enumerate(options):
        target = best(i, used)
        for r, c in opts:  # first best option in the fixed order wins a tie
            if used >> c & 1:
                continue
            a, b, d = best(i + 1, used | 1 << c)
            if (a + 1, b + r.score, d - r.distance_m) == target:
                chosen[i] = (r, c)
                used |= 1 << c
                break
        # otherwise: leaving request i unassigned was (one of) the best
    return chosen
