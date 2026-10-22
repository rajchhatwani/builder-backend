"""M3 acceptance: golden files, byte-identical determinism, and generated code that compiles,
passes ruff, imports cleanly, builds its OpenAPI schema and renders its migration to SQL.

Set UPDATE_GOLDEN=1 to rewrite tests/golden/ after a deliberate template change, then review
the diff.
"""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app.core.generator import InvalidSpecError, generate
from app.core.spec_models import Spec

TESTS = Path(__file__).resolve().parent.parent
FIXTURES = TESTS / "fixtures" / "specs"
GOLDEN = TESTS / "golden"
NAMES = ["minimal", "blog", "library"]


def load_spec(name: str) -> Spec:
    return Spec.model_validate_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def write_tree(root: Path, files: dict[str, str]) -> None:
    for path, content in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")


def run(args: list[str], cwd: Path, **extra_env: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["DATABASE_URL"] = "postgresql+asyncpg://user:pass@localhost:5432/example_test"
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=120
    )


@pytest.fixture(scope="module", params=NAMES)
def project(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Any:
    name: str = request.param
    files = generate(load_spec(name))
    root = tmp_path_factory.mktemp(name)
    write_tree(root, files)
    return name, files, root


# --- golden files and determinism -------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_output_matches_golden_files(name: str) -> None:
    files = generate(load_spec(name))
    golden_root = GOLDEN / name

    if os.environ.get("UPDATE_GOLDEN") == "1":
        if golden_root.exists():
            for old in sorted(golden_root.rglob("*"), reverse=True):
                old.unlink() if old.is_file() else old.rmdir()
        write_tree(golden_root, files)

    expected = {
        p.relative_to(golden_root).as_posix(): p.read_text(encoding="utf-8")
        for p in golden_root.rglob("*")
        if p.is_file()
    }
    assert sorted(files) == sorted(expected), "file list differs from golden (UPDATE_GOLDEN=1?)"
    for path, content in files.items():
        assert content == expected[path], f"{path} differs from golden"


@pytest.mark.parametrize("name", NAMES)
def test_same_spec_gives_byte_identical_output_in_the_same_order(name: str) -> None:
    first = generate(load_spec(name))
    second = generate(load_spec(name))

    assert list(first.items()) == list(second.items())
    assert list(first) == sorted(first)


def test_input_ordering_of_entities_and_relations_does_not_change_output() -> None:
    spec = load_spec("library")
    shuffled = spec.model_copy(
        update={
            "entities": list(reversed(spec.entities)),
            "relations": list(reversed(spec.relations)),
        }
    )

    assert generate(shuffled) == generate(spec)


def test_invalid_spec_is_rejected_with_all_issues() -> None:
    spec = load_spec("blog")
    spec.entities[0].fields[0].name = "class"
    spec.relations[0].to_entity = "Ghost"

    with pytest.raises(InvalidSpecError) as excinfo:
        generate(spec)

    assert {i.code for i in excinfo.value.issues} == {"reserved_word", "unknown_entity"}


# --- the generated code is real ---------------------------------------------------------


def test_generated_python_compiles(project: Any) -> None:
    _, files, _ = project
    for path, content in files.items():
        if path.endswith(".py"):
            compile(content, path, "exec")


def test_generated_project_passes_ruff(project: Any) -> None:
    _, _, root = project

    result = run(["-m", "ruff", "check", "--no-cache", "."], root)

    assert result.returncode == 0, result.stdout + result.stderr


def test_generated_app_imports_configures_mappers_and_builds_openapi(project: Any) -> None:
    name, files, root = project
    script = (
        "import json, app.main\n"
        "from sqlalchemy.orm import configure_mappers\n"
        "configure_mappers()\n"
        "print(json.dumps(sorted(app.main.app.openapi()['paths'])))\n"
    )

    result = run(["-c", script], root)

    assert result.returncode == 0, result.stderr
    paths = json.loads(result.stdout.strip().splitlines()[-1])
    assert "/health" in paths
    spec = load_spec(name)
    for entity in spec.entities:
        if entity.options.operations:
            assert f"/{entity.plural_path}" in paths or (
                f"/{entity.plural_path}/{{item_id}}" in paths
            )


def test_initial_migration_renders_valid_sql_for_every_table(project: Any) -> None:
    name, _, root = project

    result = run(["-m", "alembic", "upgrade", "head", "--sql"], root)

    assert result.returncode == 0, result.stderr
    spec = load_spec(name)
    for entity in spec.entities:
        assert f"CREATE TABLE {entity.table_name} (" in result.stdout
    for relation in spec.relations:
        if relation.kind == "many_to_many":
            from_table = next(e.table_name for e in spec.entities if e.name == relation.from_entity)
            assert f"CREATE TABLE {from_table}_{relation.from_name} (" in result.stdout


def test_library_migration_has_expected_constraints() -> None:
    files = generate(load_spec("library"))
    migration = files["alembic/versions/0001_initial.py"]

    assert 'sa.UniqueConstraint("isbn", name="uq_books_isbn")' in migration
    assert 'op.create_index("ix_books_title", "books", ["title"])' in migration
    assert '"fk_books_author_id_authors"' in migration
    assert 'ondelete="RESTRICT"' in migration
    assert '"fk_members_sponsor_id_members"' in migration  # self-referential
    assert 'sa.UniqueConstraint("member_id", name="uq_profiles_member_id")' in migration  # 1:1
    assert 'name="pk_books_borrowers"' in migration  # many_to_many join table
    assert "postgresql.JSONB()" in migration


def test_disabled_operations_produce_no_routes() -> None:
    router = generate(load_spec("library"))["app/routers/shelves.py"]

    assert "@router.get" in router
    assert "@router.post" in router
    for verb in ("put", "patch", "delete", "head"):
        assert f"@router.{verb}" not in router


def test_entity_without_create_gets_a_skipped_smoke_test() -> None:
    spec = load_spec("blog")
    spec.entities[0].options.operations = ["list", "get"]  # Comment: no create

    files = generate(spec)

    assert "pytest.skip(" in files["tests/test_comments.py"]
    assert "def make_comments" not in files["tests/_factories.py"]


# --- values from the spec can never become code -----------------------------------------

_NASTY = [
    "'; import os; os.system('x') #",
    '"""\nimport os\n"""',
    "back\\slash \\' \\\" end",
    "{{ 7 * 7 }} {% raw %}",
    "unicode é 中 \U0001f600",
]


def nasty_spec() -> Spec:
    return Spec.model_validate(
        {
            "project": {
                "name": 'Evil"); import os; print("x',
                "slug": "evil",
                "description": "{{ 7 * 7 }} {% for x in y %} \"\"\" ''' \\",
            },
            "entities": [
                {
                    "name": "Note",
                    "table_name": "notes",
                    "plural_path": "notes",
                    "fields": [
                        {"name": f"f{i}", "type": "text", "default": value}
                        for i, value in enumerate(_NASTY)
                    ]
                    + [
                        {
                            "name": "kind",
                            "type": "enum",
                            "enum_values": ["a-b", "c.d", "e_f"],
                            "default": "a-b",
                        },
                        {"name": "blob", "type": "json", "default": {"k": _NASTY}},
                    ],
                }
            ],
        }
    )


def test_hostile_values_stay_data_in_generated_code(tmp_path: Path) -> None:
    files = generate(nasty_spec())
    write_tree(tmp_path, files)

    for path, content in files.items():
        if path.endswith(".py"):
            tree = ast.parse(content, path)
            imported = {
                alias.name.split(".")[0]
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            }
            assert "os" not in imported, path
    assert "{{ 7 * 7 }}" in files["README.md"]
    assert "49" not in files["README.md"]

    script = (
        "import json\n"
        "from app.schemas.notes import NoteCreate\n"
        "note = NoteCreate()\n"
        "print(json.dumps([getattr(note, f'f{i}') for i in range(5)] + [note.kind, note.blob]))\n"
    )
    result = run(["-c", script], tmp_path)

    assert result.returncode == 0, result.stderr
    values = json.loads(result.stdout.strip().splitlines()[-1])
    assert values == [*_NASTY, "a-b", {"k": _NASTY}]
    assert run(["-m", "ruff", "check", "--no-cache", "."], tmp_path).returncode == 0


# --- archive helpers --------------------------------------------------------------------


def test_zip_is_deterministic_and_rooted_under_the_slug() -> None:
    import io
    import zipfile

    from app.core.generator.archive import build_zip, manifest

    files = generate(load_spec("blog"))

    first = build_zip("blog", files)
    second = build_zip("blog", dict(reversed(list(files.items()))))

    assert first == second
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        assert archive.namelist() == [f"blog/{p}" for p in sorted(files)]
        assert archive.read("blog/app/main.py").decode() == files["app/main.py"]
    assert [m["path"] for m in manifest(files)] == sorted(files)


def test_project_without_entities_generates_clean_code(tmp_path: Path) -> None:
    spec = Spec.model_validate({"project": {"name": "Empty", "slug": "empty"}})
    files = generate(spec)
    write_tree(tmp_path, files)

    assert run(["-m", "ruff", "check", "--no-cache", "."], tmp_path).returncode == 0
    script = "import app.main; print(sorted(app.main.app.openapi()['paths']))"
    result = run(["-c", script], tmp_path)
    assert result.returncode == 0, result.stderr
    assert "/health" in result.stdout
