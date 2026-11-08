"""Every generated project has exactly one linear Alembic chain, whatever features are enabled."""

import re
from pathlib import Path

import pytest

from app.core.generator import generate
from app.core.generator.engine import chain_migrations
from app.core.spec_models import Spec

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"
NAMES = sorted(p.stem for p in FIXTURES.glob("*.json"))
_REV = re.compile(r'^revision: str = "([^"]+)"$', re.M)
_DOWN = re.compile(r'^down_revision: str \| None = (None|"([^"]+)")$', re.M)


def graph(files: dict[str, str]) -> dict[str, str | None]:
    """revision id -> parent id, read from the rendered migration files."""
    out: dict[str, str | None] = {}
    for path, text in files.items():
        if not re.match(r"^alembic/versions/[^/]+\.py$", path):
            continue
        rev = _REV.search(text)
        down = _DOWN.search(text)
        assert rev is not None and down is not None, path
        assert rev.group(1) not in out, f"duplicate revision {rev.group(1)}"
        out[rev.group(1)] = down.group(2)
    return out


def assert_linear(g: dict[str, str | None]) -> None:
    assert g, "no migrations generated"
    roots = [r for r, p in g.items() if p is None]
    assert len(roots) == 1, f"roots: {roots}"
    assert all(p is None or p in g for p in g.values()), "dangling parent"
    parents = [p for p in g.values() if p is not None]
    assert len(parents) == len(set(parents)), "two revisions share a parent (multiple heads)"
    heads = [r for r in g if r not in parents]
    assert len(heads) == 1, f"heads: {heads}"
    seen: set[str] = set()
    cur: str | None = heads[0]
    while cur is not None:
        assert cur not in seen, "cycle"
        seen.add(cur)
        cur = g[cur]
    assert seen == set(g), "chain does not reach every revision"


@pytest.mark.parametrize("name", NAMES)
def test_fixture_has_one_linear_chain(name: str) -> None:
    spec = Spec.model_validate_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    assert_linear(graph(generate(spec)))


def test_combined_spec_chain_is_ordered_by_revision_id() -> None:
    spec = Spec.model_validate_json((FIXTURES / "combined_async.json").read_text(encoding="utf-8"))
    g = graph(generate(spec))
    assert_linear(g)
    for rev in ("0009", "0012", "0013", "0016"):
        assert rev in g
    assert g["0012"] == "0009" and g["0013"] == "0012" and g["0016"] == "0013"


def test_duplicate_revision_id_is_rejected() -> None:
    body = 'revision: str = "0042"\ndown_revision: str | None = None\n'
    with pytest.raises(RuntimeError, match="share revision id"):
        chain_migrations({"alembic/versions/0042_a.py": body, "alembic/versions/0042_b.py": body})


def test_chain_rewrites_parents_and_revises_header() -> None:
    def mig(rev: str, parent: str) -> str:
        return (
            f"Revises: {parent}\nrevision: str = \"{rev}\"\n"
            f"down_revision: str | None = \"{parent}\"\n"
        )

    files = {
        "alembic/versions/0001_a.py": mig("0001", "zzz"),
        "alembic/versions/0005_b.py": mig("0005", "0001"),
        "alembic/versions/0009_c.py": mig("0009", "0001"),
    }
    chain_migrations(files)
    assert 'down_revision: str | None = None' in files["alembic/versions/0001_a.py"]
    assert "Revises: \n" not in files["alembic/versions/0001_a.py"]
    assert 'down_revision: str | None = "0005"' in files["alembic/versions/0009_c.py"]
    assert "Revises: 0005" in files["alembic/versions/0009_c.py"]
