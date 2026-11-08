"""Enumerate every HTTP route of the app, including those mounted through included routers.

FastAPI wraps an included router in an `_IncludedRouter`, so `isinstance(r, APIRoute)` over
`app.routes` finds nothing under it (review F-001). Walking `effective_route_contexts()` does.
"""

from dataclasses import dataclass

from fastapi.routing import APIRoute

from app.main import app

# A floor, not the exact count: a walker that sees fewer routes than this walks nothing.
MIN_EXPECTED_ROUTES = 100


@dataclass(frozen=True)
class RouteInfo:
    method: str
    path: str
    calls: frozenset[object]  # every dependency callable, route-level and router-level
    names: frozenset[str]  # their qualified names


def _calls(dependant: object) -> set[object]:
    found: set[object] = set()
    stack = [dependant]
    while stack:
        d = stack.pop()
        found.add(d.call)  # type: ignore[attr-defined]
        stack.extend(d.dependencies)  # type: ignore[attr-defined]
    return found


def _info(path: str, methods: set[str], calls: set[object]) -> list[RouteInfo]:
    names = frozenset(getattr(c, "__qualname__", "") for c in calls if c)
    return [
        RouteInfo(m, path, frozenset(c for c in calls if c), names)
        for m in sorted(methods - {"HEAD", "OPTIONS"})
    ]


def all_routes() -> list[RouteInfo]:
    out: list[RouteInfo] = []
    for r in app.routes:
        if type(r).__name__ == "_IncludedRouter":
            for c in r.effective_route_contexts():  # type: ignore[attr-defined]
                extra = {getattr(d, "dependency", None) for d in c.dependencies}
                out += _info(c.path, set(c.methods), _calls(c.dependant) | extra)
        elif isinstance(r, APIRoute):
            out += _info(r.path, set(r.methods), _calls(r.dependant))
    assert len(out) > MIN_EXPECTED_ROUTES, f"route walker saw only {len(out)} routes"
    return out
