"""B4-1: pure import core (parse caps, mapping, coercion, dedupe) and the connector skeleton."""

from dataclasses import dataclass, field, replace

import pytest

from app.core import connectors as cn
from app.core import data_import as di
from app.core.spec_models import SpecEntity, SpecField


def entity() -> SpecEntity:
    return SpecEntity(
        name="Contact",
        table_name="contacts",
        plural_path="contacts",
        fields=[
            SpecField(name="full_name", type="string", required=True, max_length=10),
            SpecField(name="email", type="string", unique=True),
            SpecField(name="age", type="integer", min_value=0, max_value=120),
            SpecField(name="tier", type="enum", enum_values=["free", "pro"]),
        ],
    )


def test_parse_bom_delimiter_and_blank_lines() -> None:
    p = di.parse_csv("﻿Name;Age\r\nAnn;3\r\n\r\nBob;4\r\n".encode())
    assert p.headers == ["Name", "Age"]
    assert p.rows == [{"Name": "Ann", "Age": "3"}, {"Name": "Bob", "Age": "4"}]
    assert di.parse_csv(b"a\tb\n1\t2\n").rows == [{"a": "1", "b": "2"}]
    assert di.parse_csv(b'a,"b;c"\n1,2\n').headers == ["a", "b;c"]


def test_parse_caps_and_malformed() -> None:
    with pytest.raises(di.ImportDataError) as e:
        di.parse_csv(b"a\n" + b"x" * 50, max_bytes=10)
    assert e.value.code == "import_too_large"
    with pytest.raises(di.ImportDataError) as e:
        di.parse_csv(b"a\n1\n2\n3\n", max_rows=2)
    assert e.value.code == "import_too_large"
    wide = ",".join(f"c{i}" for i in range(di.MAX_COLUMNS + 1))
    with pytest.raises(di.ImportDataError) as e:
        di.parse_csv(wide.encode())
    assert e.value.code == "import_too_large"
    for bad in (b"", b"\xff\xfe\x00bad", b"a,a\n1,2\n", b"a,\n1,2\n", b"a,b\n1,2,3\n", b'a,b\n"x,2\n'):
        with pytest.raises(di.ImportDataError) as e:
            di.parse_csv(bad)
        assert e.value.code == "import_bad_csv", bad


def test_neutralize_formula() -> None:
    for s in ("=1+1", "+1", "-1", "@SUM(A1)", "\tx", "\rx"):
        assert di.neutralize_formula(s) == "'" + s
    assert di.neutralize_formula("hello") == "hello"
    assert di.neutralize_formula(5) == 5
    # parsing never rewrites a cell
    assert di.parse_csv(b"a\n=1+1\n").rows == [{"a": "=1+1"}]


def test_suggest_and_clean_mapping() -> None:
    assert di.suggest_mapping(["Full Name", "EMAIL", "x"], entity()) == {
        "full_name": "Full Name",
        "email": "EMAIL",
    }
    assert di.suggest_mapping(["FULL_NAME"], entity()) == {"full_name": "FULL_NAME"}
    assert di.clean_mapping({"age": "A", "tier": None}, ["A"], entity()) == {"age": "A"}
    for bad in ({"nope": "A"}, {"age": "Z"}, ["x"]):
        with pytest.raises(di.ImportDataError) as e:
            di.clean_mapping(bad, ["A"], entity())
        assert e.value.code == "import_bad_mapping"


def f(t: str, **kw: object) -> SpecField:
    return SpecField(name="v", type=t, **kw)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field_", "value", "expected"),
    [
        (f("string"), "hi", "hi"),
        (f("text"), "line\nbreak", "line\nbreak"),
        (f("integer"), " 42 ", 42),
        (f("bigint"), "9000000000", 9000000000),
        (f("float"), "1.5", 1.5),
        (f("decimal"), "1.50", "1.50"),
        (f("boolean"), "Yes", True),
        (f("boolean"), "0", False),
        (f("date"), "2026-11-09", "2026-11-09"),
        (f("datetime"), "2026-11-09T10:00:00+02:00", "2026-11-09T08:00:00+00:00"),
        (f("datetime"), "2026-11-09T10:00:00", "2026-11-09T10:00:00+00:00"),
        (f("uuid"), "12345678-1234-5678-1234-567812345678", "12345678-1234-5678-1234-567812345678"),
        (f("json"), '{"a": 1}', {"a": 1}),
        (f("enum", enum_values=["a", "b"]), "b", "b"),
        (f("string"), "", None),
    ],
)
def test_coerce_ok(field_: SpecField, value: object, expected: object) -> None:
    assert di.coerce(value, field_) == expected


@pytest.mark.parametrize(
    ("field_", "value", "code"),
    [
        (f("string", required=True), "  ", "required"),
        (f("string", max_length=3), "abcd", "too_long"),
        (f("integer"), "1.5", "invalid_integer"),
        (f("integer"), "99999999999", "out_of_range"),
        (f("integer", min_value=0), "-1", "below_min"),
        (f("integer", max_value=10), "11", "above_max"),
        (f("float", max_value=1), "2", "above_max"),
        (f("float"), "nan", "invalid_number"),
        (f("decimal"), "abc", "invalid_number"),
        (f("boolean"), "maybe", "invalid_boolean"),
        (f("date"), "09/11/2026", "invalid_date"),
        (f("datetime"), "yesterday", "invalid_datetime"),
        (f("uuid"), "nope", "invalid_uuid"),
        (f("json"), "{bad", "invalid_json"),
        (f("enum", enum_values=["a"]), "z", "invalid_enum"),
        (f("file"), "x.png", "unsupported_type"),
    ],
)
def test_coerce_errors(field_: SpecField, value: object, code: str) -> None:
    with pytest.raises(ValueError, match=code):
        di.coerce(value, field_)


def test_default_fills_blank() -> None:
    assert di.coerce("", f("integer", default=7, required=True)) == 7


def test_validate_rows_accepts_and_rejects_with_field_errors() -> None:
    rows = [
        {"N": "Ann", "A": "30", "E": "a@x.io", "T": "pro"},
        {"N": "", "A": "abc", "E": "b@x.io", "T": "gold"},
    ]
    res = di.validate_rows(rows, {"full_name": "N", "age": "A", "email": "E", "tier": "T"}, entity())
    assert res[0].accepted and res[0].record == {"full_name": "Ann", "email": "a@x.io", "age": 30, "tier": "pro"}
    assert not res[1].accepted and res[1].record is None
    assert {(e.field, e.code) for e in res[1].errors} == {
        ("full_name", "required"),
        ("age", "invalid_integer"),
        ("tier", "invalid_enum"),
    }
    assert [r.row_no for r in res] == [1, 2]


def test_dedupe_key_stable_and_scoped() -> None:
    e = entity()
    a = {"full_name": "Ann", "email": "a@x.io", "age": 3, "tier": None}
    b = {"tier": None, "age": 99, "email": "a@x.io", "full_name": "Other"}
    assert di.dedupe_key(e, a) == di.dedupe_key(e, b)  # unique field decides
    assert len(di.dedupe_key(e, a)) == 64
    no_unique = SpecEntity(name="N", table_name="n", plural_path="n", fields=[SpecField(name="x", type="string")])
    assert di.dedupe_key(no_unique, {"x": "1"}) != di.dedupe_key(no_unique, {"x": "2"})
    assert di.dedupe_key(no_unique, {"x": "1"}) == di.dedupe_key(no_unique, {"x": "1"})
    # all unique fields blank: falls back to the whole record
    assert di.dedupe_key(e, {"full_name": "A", "email": None}) != di.dedupe_key(e, {"full_name": "B", "email": None})
    assert di.dedupe_key(e, a, ["full_name"]) != di.dedupe_key(e, a)


# -- connectors ----------------------------------------------------------------------------------


@dataclass
class FakeConnector:
    """In-memory pull connector: a changelog of (seq, key, data, deleted)."""

    log: list[tuple[int, str, dict[str, object], bool]] = field(default_factory=list)
    page: int = 2
    kind: str = "fake"

    def fetch(self, cursor: cn.CursorState) -> tuple[list[cn.ConnectorRecord], cn.CursorState]:
        after = int(cursor.position or 0)
        items = [x for x in self.log if x[0] > after]
        if cursor.mode == "reconcile":
            latest: dict[str, tuple[int, str, dict[str, object], bool]] = {}
            for x in self.log:
                latest[x[1]] = x
            items = [x for x in latest.values() if not x[3] and x[0] > after]
        chunk = items[: self.page]
        if not cursor.tombstones:
            chunk_out = [x for x in chunk if not x[3]]
        else:
            chunk_out = chunk
        recs = [cn.ConnectorRecord(key=x[1], data=x[2], deleted=x[3]) for x in chunk_out]
        pos = str(chunk[-1][0]) if chunk else str(after)
        return recs, replace(cursor, position=pos, done=len(items) <= self.page)


def test_fake_connector_cursor_advances_and_tombstones() -> None:
    c = FakeConnector(log=[(1, "a", {"v": 1}, False), (2, "b", {"v": 2}, False), (3, "c", {"v": 3}, False)])
    recs, state = cn.drain(c)
    assert [r.key for r in recs] == ["a", "b", "c"] and state.position == "3" and state.done
    # incremental from the saved cursor: only the new change, including a tombstone
    c.log += [(4, "b", {}, True), (5, "d", {"v": 4}, False)]
    inc = replace(state, mode="incremental", tombstones=True, done=False)
    recs, state2 = cn.drain(c, inc)
    assert [(r.key, r.deleted) for r in recs] == [("b", True), ("d", False)]
    assert state2.position == "5"
    # without tombstone support the deletion is simply not reported
    recs, _ = cn.drain(c, replace(state, mode="incremental", done=False))
    assert [r.key for r in recs] == ["d"]
    # reconcile: keys we hold that the source no longer lists
    listing, _ = cn.drain(c, cn.CursorState(mode="reconcile"))
    assert cn.missing_keys({"a", "b", "c", "d"}, listing) == {"b"}


def test_file_connector_pages_and_registry() -> None:
    assert cn.REGISTRY["file"] is cn.FileConnector
    csv_bytes = b"full_name,age\nA,1\nB,2\nC,x\nD,4\nE,5\n"
    c = cn.FileConnector(entity(), {"full_name": "full_name", "age": "age"}, csv_bytes, page_size=2)
    page1, s1 = c.fetch(cn.CursorState())
    assert [r.key for r in page1] == ["1", "2"] and s1.position == "2" and not s1.done
    recs, final = cn.drain(c)
    assert [r.key for r in recs] == ["1", "2", "4", "5"]  # row 3 is invalid, not emitted
    assert final.done


def test_hostile_numbers_and_json_are_rejected_not_crashing() -> None:
    from app.core.data_import import coerce
    from app.core.spec_models import SpecField

    dec = SpecField(name="amount", type="decimal")
    js = SpecField(name="meta", type="json")
    for bad in ("1e999999", "-1e999999"):
        try:
            coerce(bad, dec)
        except ValueError as e:
            assert str(e) == "out_of_range"
        else:
            raise AssertionError("accepted")
    for bad in ("[" * 5000, "NaN", '{"a": Infinity}', "[" * 40 + "]" * 40):
        try:
            coerce(bad, js)
        except ValueError as e:
            assert str(e) == "invalid_json"
        else:
            raise AssertionError("accepted " + bad[:10])
    assert coerce('{"a": [1, 2]}', js) == {"a": [1, 2]}
