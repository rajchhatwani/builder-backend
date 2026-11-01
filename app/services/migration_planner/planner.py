# ruff: noqa: E501
"""plan_migration(old_spec, new_spec): pure, deterministic spec-diff migration planner (block F4).

No database, no clock, no randomness. Same inputs -> byte-identical plan JSON, whatever the order of
entities, fields or relations in the inputs. Renames are NEVER guessed: only declared ones are applied.
"""

from typing import Any

from app.core.spec_models import Spec

from . import classify as C
from .diff import Aligned, Col, Rel, Snapshot, Table, apply_renames, coerce_spec, snapshot
from .model import PHASES, MigrationPlan, PlanStep, Safety, StepKind
from .rename import parse_renames


def _q(x: str) -> str:
    return '"' + x.replace('"', '""') + '"'


class _Builder:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def add(
        self,
        phase: str,
        kind: StepKind,
        entity: str,
        table: str,
        field: str | None,
        safety: Safety,
        reason: str,
        *,
        action: str | None = None,
        strategy: str | None = None,
        sql: str | None = None,
        note: str | None = None,
    ) -> None:
        self.rows.append(
            {
                "phase": PHASES[phase],
                "kind": kind,
                "entity": entity,
                "table": table,
                "field": field,
                "safety": safety,
                "reason": reason,
                "suggested_action": action,
                "backfill_strategy": strategy,
                "sql_hint": sql,
                "note": note,
            }
        )

    def steps(self) -> list[PlanStep]:
        ordered = sorted(
            self.rows,
            key=lambda r: (r["phase"], r["entity"], r["table"], r["field"] or "", r["kind"].value, r["reason"]),
        )
        return [PlanStep(seq=i + 1, **r) for i, r in enumerate(ordered)]


def _col_ddl(c: Col, with_not_null: bool) -> str:
    parts = [_q(c.name), C.pg_type(c)]
    if c.default is not None:
        parts.append(f"DEFAULT {C.literal(c.default)}")
    if with_not_null and c.required:
        parts.append("NOT NULL")
    return " ".join(parts)


def _sig(t: Table) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((c.name, c.type) for c in t.cols))


def _schema_sig(s: Snapshot) -> tuple[Any, ...]:
    return (
        s.multi_tenant,
        tuple(sorted((n, t.table, t.soft_delete, tuple(sorted(t.cols, key=lambda c: c.name))) for n, t in s.tables.items())),
        tuple(sorted(s.rels.items())),
    )


def _create_table(b: _Builder, t: Table, tenant: bool, note: str | None = None) -> None:
    cols = ["id uuid PRIMARY KEY"] + [_col_ddl(c, True) for c in sorted(t.cols, key=lambda c: c.name)]
    if tenant:
        cols.append("tenant_id uuid NOT NULL")
    if t.soft_delete:
        cols.append("deleted_at timestamptz")
    b.add(
        "create", StepKind.create_table, t.entity, t.table, None, Safety.safe,
        f"new entity {t.entity}",
        sql=f"CREATE TABLE {_q(t.table)} ({', '.join(cols)})", note=note,
    )


def _drop_table(b: _Builder, t: Table, action: str | None = None, why: str = "entity removed") -> None:
    b.add(
        "destructive", StepKind.drop_table, t.entity, t.table, None, Safety.destructive,
        f"{why}: every row of {t.table} is lost",
        action=action or "export the data first, then confirm the drop",
        sql=f"DROP TABLE {_q(t.table)}",
    )


def _add_column(b: _Builder, t: Table, c: Col, note: str | None = None) -> None:
    ddl = f"ALTER TABLE {_q(t.table)} ADD COLUMN {_col_ddl(c, False)}"
    if c.required and not C.has_default(c):
        b.add(
            "backfill", StepKind.add_column, t.entity, t.table, c.name, Safety.backfill,
            f"new required column {t.entity}.{c.name} has no default; existing rows have no value for it",
            strategy=(
                f"1) add the column nullable; 2) UPDATE {_q(t.table)} SET {_q(c.name)} = <value> WHERE {_q(c.name)} IS NULL; "
                f"3) ALTER COLUMN SET NOT NULL"
            ),
            action="choose the value existing rows get (or give the field a default)",
            sql=f"{ddl};\nUPDATE {_q(t.table)} SET {_q(c.name)} = <value> WHERE {_q(c.name)} IS NULL;\n"
            f"ALTER TABLE {_q(t.table)} ALTER COLUMN {_q(c.name)} SET NOT NULL",
            note=note,
        )
    else:
        sql = ddl + (" NOT NULL" if c.required else "")
        why = "new column with a default" if C.has_default(c) else "new nullable column"
        b.add("additive", StepKind.add_column, t.entity, t.table, c.name, Safety.safe, f"{why} {t.entity}.{c.name}", sql=sql, note=note)
    if c.unique:
        _add_unique(b, t, c.name, new_col=not (c.required or C.has_default(c)))
    elif c.indexed:
        _add_index(b, t, c.name)


def _add_unique(b: _Builder, t: Table, col: str, new_col: bool = False) -> None:
    sql = f"ALTER TABLE {_q(t.table)} ADD CONSTRAINT {_q('uq_' + t.table + '_' + col)} UNIQUE ({_q(col)})"
    if new_col:  # a fresh nullable column holds only NULLs: nothing can collide
        b.add("constrain", StepKind.add_unique, t.entity, t.table, col, Safety.safe, f"unique on new nullable column {t.entity}.{col}", sql=sql)
        return
    b.add(
        "constrain", StepKind.add_unique, t.entity, t.table, col, Safety.backfill,
        f"unique constraint on {t.entity}.{col} fails if existing rows hold duplicates",
        strategy=f"find duplicates (SELECT {_q(col)}, count(*) FROM {_q(t.table)} GROUP BY 1 HAVING count(*) > 1) and dedupe or correct them before the constraint",
        action="resolve duplicate values, then add the constraint",
        sql=sql,
    )


def _add_index(b: _Builder, t: Table, col: str) -> None:
    b.add(
        "constrain", StepKind.add_index, t.entity, t.table, col, Safety.safe, f"index on {t.entity}.{col}",
        sql=f"CREATE INDEX {_q('ix_' + t.table + '_' + col)} ON {_q(t.table)} ({_q(col)})",
    )


def _diff_column(b: _Builder, t: Table, o: Col, n: Col) -> None:
    ent, tbl, name = t.entity, t.table, n.name
    ref = f"{ent}.{name}"
    alter = f"ALTER TABLE {_q(tbl)} ALTER COLUMN {_q(name)}"
    # 1. type
    if o.type != n.type:
        if n.type == "enum" and o.type in {"string", "text"}:
            kind, safety, reason = "convert_type", Safety.backfill, f"{o.type} -> enum: existing values must all be in the list"
        else:
            kind, safety, reason = C.type_change(o, n)
        sk = StepKind(kind)
        using = f" USING {_q(name)}::{C.pg_type(n)}"
        sql = f"{alter} TYPE {C.pg_type(n)}{using}"
        phase = "destructive" if safety == Safety.destructive else ("backfill" if safety == Safety.backfill else "additive")
        b.add(
            phase, sk, ent, tbl, name, safety, f"{ref}: {reason}",
            action="declare the intent: migrate data to a new field and drop the old one" if safety == Safety.destructive else None,
            strategy=(
                f"check what does not convert: SELECT count(*) FROM {_q(tbl)} WHERE {_q(name)} IS NOT NULL AND <cast fails>; "
                f"clean or map those rows, then run ALTER ... TYPE ... USING"
            ) if safety == Safety.backfill else None,
            sql=sql,
        )
    else:
        if n.type == "string":
            lc = C.length_change(o, n)
            if lc:
                kind, safety, reason = lc
                b.add(
                    "destructive" if safety == Safety.destructive else "additive", StepKind(kind), ent, tbl, name, safety, f"{ref}: {reason}",
                    action="shorten only after checking the longest stored value" if safety == Safety.destructive else None,
                    sql=f"{alter} TYPE {C.pg_type(n)}",
                )
        if n.type == "enum":
            added, removed = C.enum_change(o, n)
            if added:
                b.add(
                    "additive", StepKind.add_enum_value, ent, tbl, name, Safety.safe, f"{ref}: new values {added}",
                    note="no column-level change in the generated schema",
                )
            if removed:
                b.add(
                    "destructive", StepKind.drop_enum_value, ent, tbl, name, Safety.destructive,
                    f"{ref}: values {removed} removed; rows still holding them become invalid",
                    action=f"migrate rows holding {removed} to another value first",
                    sql=f"SELECT count(*) FROM {_q(tbl)} WHERE {_q(name)} IN ({', '.join(C.literal(v) for v in removed)})",
                )
    # 2. nullability
    if not o.required and n.required:
        strat = (
            f"UPDATE {_q(tbl)} SET {_q(name)} = {C.literal(n.default)} WHERE {_q(name)} IS NULL"
            if C.has_default(n) else f"UPDATE {_q(tbl)} SET {_q(name)} = <value> WHERE {_q(name)} IS NULL"
        )
        b.add(
            "constrain", StepKind.set_not_null, ent, tbl, name, Safety.backfill,
            f"{ref} becomes required; rows holding NULL would violate it",
            strategy=strat, action="fill the NULLs (with the default or a chosen value), then set NOT NULL",
            sql=f"{strat};\n{alter} SET NOT NULL",
        )
    elif o.required and not n.required:
        b.add("additive", StepKind.relax_not_null, ent, tbl, name, Safety.safe, f"{ref} no longer required", sql=f"{alter} DROP NOT NULL")
    # 3. default
    if o.default != n.default:
        if n.required and o.default is not None and n.default is not None:
            b.add(
                "backfill", StepKind.change_default, ent, tbl, name, Safety.backfill,
                f"{ref}: default {o.default!r} -> {n.default!r} on a required field changes what a missing value means",
                strategy="decide whether existing rows keep the old value or are rewritten to the new default; UPDATE accordingly",
                action="state whether existing rows should change",
                sql=f"{alter} SET DEFAULT {C.literal(n.default)}",
            )
        else:
            sql = f"{alter} SET DEFAULT {C.literal(n.default)}" if n.default is not None else f"{alter} DROP DEFAULT"
            b.add("additive", StepKind.change_default, ent, tbl, name, Safety.safe, f"{ref}: default {o.default!r} -> {n.default!r}", sql=sql)
    # 4. unique / index
    if not o.unique and n.unique:
        _add_unique(b, t, name)
    elif o.unique and not n.unique:
        b.add(
            "constrain", StepKind.drop_unique, ent, tbl, name, Safety.safe, f"{ref} no longer unique",
            note="duplicates become possible; consumers relying on uniqueness may break",
            sql=f"ALTER TABLE {_q(tbl)} DROP CONSTRAINT {_q('uq_' + tbl + '_' + name)}",
        )
    if o.indexed != n.indexed and not (o.unique or n.unique):
        if n.indexed:
            _add_index(b, t, name)
        else:
            b.add("constrain", StepKind.drop_index, ent, tbl, name, Safety.safe, f"index on {ref} removed",
                  note="queries filtering on it may slow down", sql=f"DROP INDEX {_q('ix_' + tbl + '_' + name)}")


def _pair_renames(dropped: list[str], added: list[str], old_cols: list[Col], new_cols: list[Col]) -> dict[str, str]:
    """Undeclared drop+add pairs with the same type: {dropped name: added name}. Flag only, never apply."""
    odx = {c.name: (i, c) for i, c in enumerate(old_cols)}
    ndx = {c.name: (i, c) for i, c in enumerate(new_cols)}
    pairs: dict[str, str] = {}
    by_type: dict[str, tuple[list[str], list[str]]] = {}
    for d in dropped:
        by_type.setdefault(odx[d][1].type, ([], []))[0].append(d)
    for a in added:
        by_type.setdefault(ndx[a][1].type, ([], []))[1].append(a)
    for ds, as_ in by_type.values():
        if len(ds) == 1 and len(as_) == 1:
            pairs[ds[0]] = as_[0]
        else:
            for d in ds:
                for a in as_:
                    if odx[d][0] == ndx[a][0]:
                        pairs[d] = a
    return pairs


def _diff_table(b: _Builder, o: Table, n: Table) -> None:
    oc = {c.name: c for c in o.cols}
    nc = {c.name: c for c in n.cols}
    dropped = sorted(set(oc) - set(nc))
    added = sorted(set(nc) - set(oc))
    pairs = _pair_renames(dropped, added, o.cols, n.cols)
    flagged_new = set(pairs.values())
    for name in dropped:
        action = None
        if name in pairs:
            action = "declare a rename" + f" ({n.entity}.{name} -> {pairs[name]}) if this is the same data, otherwise confirm the drop"
        b.add(
            "destructive", StepKind.drop_column, n.entity, n.table, name, Safety.destructive,
            f"column {n.entity}.{name} removed: its data is lost",
            action=action or "export the column first, then confirm the drop",
            sql=f"ALTER TABLE {_q(n.table)} DROP COLUMN {_q(name)}",
        )
    for name in added:
        inv = {v: k for k, v in pairs.items()}
        _add_column(b, n, nc[name], note=f"looks like a rename of {inv[name]}; undeclared, so planned as drop + add" if name in flagged_new else None)
    for name in sorted(set(oc) & set(nc)):
        _diff_column(b, n, oc[name], nc[name])
    if not o.soft_delete and n.soft_delete:
        b.add("additive", StepKind.add_column, n.entity, n.table, "deleted_at", Safety.safe, f"soft delete enabled on {n.entity}",
              sql=f"ALTER TABLE {_q(n.table)} ADD COLUMN deleted_at timestamptz")
    elif o.soft_delete and not n.soft_delete:
        b.add("destructive", StepKind.drop_column, n.entity, n.table, "deleted_at", Safety.destructive,
              f"soft delete disabled on {n.entity}: deletion markers are lost, soft-deleted rows turn into live rows",
              action="hard-delete the soft-deleted rows first if they should stay gone",
              sql=f"ALTER TABLE {_q(n.table)} DROP COLUMN deleted_at")


def _fk_sql(child: Table, parent: Table, r: Rel) -> str:
    action = {"cascade": "CASCADE", "set_null": "SET NULL", "restrict": "RESTRICT"}.get(r.on_delete, "RESTRICT")
    return (
        f"ALTER TABLE {_q(child.table)} ADD CONSTRAINT {_q('fk_' + child.table + '_' + r.fk_column)} "
        f"FOREIGN KEY ({_q(r.fk_column)}) REFERENCES {_q(parent.table)} (id) ON DELETE {action}"
    )


def _diff_relations(b: _Builder, old: Snapshot, new: Snapshot, replaced: set[str]) -> None:
    for key in sorted(set(old.rels) | set(new.rels)):
        o, n = old.rels.get(key), new.rels.get(key)
        ends = {key[0], key[2]}
        if ends & replaced:
            continue
        if o and n and o.is_join != n.is_join:
            _rel_remove(b, old, o, new)
            _rel_add(b, old, new, n)
        elif o and not n:
            _rel_remove(b, old, o, new)
        elif n and not o:
            _rel_add(b, old, new, n)
        elif o and n:
            _rel_change(b, new, o, n)


def _rel_remove(b: _Builder, old: Snapshot, r: Rel, new: Snapshot) -> None:
    if r.from_entity not in new.tables or r.to_entity not in new.tables:
        return  # a dropped table takes the relation with it
    if r.is_join:
        b.add("destructive", StepKind.drop_table, r.from_entity, r.join_table, r.from_name, Safety.destructive,
              f"many-to-many {r.from_entity}.{r.from_name} removed: the link rows are lost",
              action="export the links first, then confirm the drop", sql=f"DROP TABLE {_q(r.join_table)}")
        return
    child = new.tables[r.to_entity]
    b.add("constrain", StepKind.drop_fk, r.to_entity, child.table, r.fk_column, Safety.safe,
          f"foreign key {r.to_entity}.{r.fk_column} removed", note="orphan rows become possible",
          sql=f"ALTER TABLE {_q(child.table)} DROP CONSTRAINT {_q('fk_' + child.table + '_' + r.fk_column)}")
    b.add("destructive", StepKind.drop_column, r.to_entity, child.table, r.fk_column, Safety.destructive,
          f"relation removed: column {r.to_entity}.{r.fk_column} and its links are lost",
          action="export the links first, then confirm the drop",
          sql=f"ALTER TABLE {_q(child.table)} DROP COLUMN {_q(r.fk_column)}")


def _rel_add(b: _Builder, old: Snapshot, new: Snapshot, r: Rel) -> None:
    if r.is_join:
        b.add("create", StepKind.create_table, r.from_entity, r.join_table, r.from_name, Safety.safe,
              f"join table for many-to-many {r.from_entity}.{r.from_name}",
              sql=f"CREATE TABLE {_q(r.join_table)} (left_id uuid NOT NULL, right_id uuid NOT NULL, PRIMARY KEY (left_id, right_id))")
        return
    if r.to_entity not in old.tables:
        return  # the FK column is part of the new table
    child, parent = new.tables[r.to_entity], new.tables[r.from_entity]
    col = r.fk_column
    if r.required:
        b.add("backfill", StepKind.add_column, r.to_entity, child.table, col, Safety.backfill,
              f"new required relation: {r.to_entity}.{col} has no value for existing rows",
              strategy=f"add {col} nullable; UPDATE {_q(child.table)} SET {_q(col)} = <parent id> for every row; then SET NOT NULL",
              action="choose the parent each existing row belongs to",
              sql=f"ALTER TABLE {_q(child.table)} ADD COLUMN {_q(col)} uuid")
    else:
        b.add("additive", StepKind.add_column, r.to_entity, child.table, col, Safety.safe,
              f"new optional relation column {r.to_entity}.{col}", sql=f"ALTER TABLE {_q(child.table)} ADD COLUMN {_q(col)} uuid")
    b.add("constrain", StepKind.add_fk, r.to_entity, child.table, col, Safety.backfill,
          f"new foreign key {r.to_entity}.{col} -> {parent.table}: existing values must reference existing rows",
          strategy=f"find orphans (SELECT count(*) FROM {_q(child.table)} c LEFT JOIN {_q(parent.table)} p ON p.id = c.{_q(col)} WHERE c.{_q(col)} IS NOT NULL AND p.id IS NULL) and fix them before the constraint",
          sql=_fk_sql(child, parent, r))
    if r.kind == "one_to_one":
        _add_unique(b, child, col, new_col=not r.required)


def _rel_change(b: _Builder, new: Snapshot, o: Rel, n: Rel) -> None:
    if n.is_join:
        return
    child, parent = new.tables[n.to_entity], new.tables[n.from_entity]
    col = n.fk_column
    if not o.required and n.required:
        b.add("constrain", StepKind.set_not_null, n.to_entity, child.table, col, Safety.backfill,
              f"relation {n.to_entity}.{col} becomes required; rows without a parent would violate it",
              strategy=f"UPDATE {_q(child.table)} SET {_q(col)} = <parent id> WHERE {_q(col)} IS NULL",
              action="assign a parent to every orphan row", sql=f"ALTER TABLE {_q(child.table)} ALTER COLUMN {_q(col)} SET NOT NULL")
    elif o.required and not n.required:
        b.add("additive", StepKind.relax_not_null, n.to_entity, child.table, col, Safety.safe,
              f"relation {n.to_entity}.{col} no longer required", sql=f"ALTER TABLE {_q(child.table)} ALTER COLUMN {_q(col)} DROP NOT NULL")
    if o.on_delete != n.on_delete:
        b.add("constrain", StepKind.alter_fk, n.to_entity, child.table, col, Safety.safe,
              f"on_delete {o.on_delete} -> {n.on_delete} for {n.to_entity}.{col}",
              note="deleting a parent now behaves differently", sql=f"-- drop and re-add the FK:\n{_fk_sql(child, parent, n)}")
    if o.kind != "one_to_one" and n.kind == "one_to_one":
        _add_unique(b, child, col)
    elif o.kind == "one_to_one" and n.kind != "one_to_one":
        b.add("constrain", StepKind.drop_unique, n.to_entity, child.table, col, Safety.safe, f"{n.to_entity}.{col} no longer one-to-one",
              note="several rows may now share a parent", sql=f"ALTER TABLE {_q(child.table)} DROP CONSTRAINT {_q('uq_' + child.table + '_' + col)}")


def _ignored(o: Spec, n: Spec, schema_equal: bool) -> list[str]:
    od, nd = o.model_dump(mode="json"), n.model_dump(mode="json")
    keys = {k for k in set(od) | set(nd) if od.get(k) != nd.get(k)}
    if "auth" in keys:
        oa, na = dict(od.get("auth") or {}), dict(nd.get("auth") or {})
        oa.pop("multi_tenant", None)
        na.pop("multi_tenant", None)
        if oa == na and (od.get("auth") is not None) == (nd.get("auth") is not None):
            keys.discard("auth")
    if not schema_equal:
        keys.discard("entities")
        keys.discard("relations")
    else:
        keys.discard("relations")  # identical schema signature: relation differences are already schema-neutral
    return sorted(keys)


def plan_migration(old_spec: Spec | dict[str, Any], new_spec: Spec | dict[str, Any], renames: list[dict[str, Any]] | None = None) -> MigrationPlan:
    """Plan the database change that turns the schema of `old_spec` into that of `new_spec`.

    `renames`: declared renames, `{"kind": "entity", "from", "to"}` or `{"entity", "from", "to"}` for a
    field. Raises MigrationPlanError on a malformed spec or rename (fail closed)."""
    o_spec = coerce_spec(old_spec, "old")
    n_spec = coerce_spec(new_spec, "new")
    so, sn = snapshot(o_spec, "old"), snapshot(n_spec, "new")
    al: Aligned = apply_renames(so, sn, parse_renames(renames))
    old = al.old
    b = _Builder()
    replaced: set[str] = set()  # entities whose table was swapped (undeclared table_name change)

    gone = sorted(set(old.tables) - set(sn.tables))
    fresh = sorted(set(sn.tables) - set(old.tables))
    twin: dict[str, str] = {}
    for g in gone:
        for f in fresh:
            if _sig(old.tables[g]) and _sig(old.tables[g]) == _sig(sn.tables[f]):
                twin[g] = f
    for g in gone:
        hint = f"declare a rename ({g} -> {twin[g]}) if this is the same data, otherwise confirm the drop" if g in twin else None
        _drop_table(b, old.tables[g], action=hint)
    twin_new = {v: k for k, v in twin.items()}
    for f in fresh:
        _create_table(b, sn.tables[f], sn.multi_tenant, note=f"looks like a rename of {twin_new[f]}; undeclared, so planned as drop + create" if f in twin_new else None)

    for name in sorted(set(old.tables) & set(sn.tables)):
        o, n = old.tables[name], sn.tables[name]
        if o.table != n.table:
            if name in al.renamed_entities:
                b.add("rename", StepKind.rename_table, name, n.table, None, Safety.safe, f"declared rename of {o.table} to {n.table}",
                      sql=f"ALTER TABLE {_q(o.table)} RENAME TO {_q(n.table)}")
            else:
                replaced.add(name)
                _drop_table(b, o, action=f"declare a rename ({o.table} -> {n.table}) if this is the same data, otherwise confirm the drop", why="table_name changed")
                _create_table(b, n, sn.multi_tenant, note=f"replaces {o.table}; undeclared, so planned as drop + create")
                continue
        for (ent, new_col), old_col in sorted(al.renamed_columns.items()):
            if ent == name:
                b.add("rename", StepKind.rename_column, name, n.table, new_col, Safety.safe, f"declared rename of {name}.{old_col} to {new_col}",
                      sql=f"ALTER TABLE {_q(n.table)} RENAME COLUMN {_q(old_col)} TO {_q(new_col)}")
        _diff_table(b, o, n)
        if not old.multi_tenant and sn.multi_tenant:
            b.add("backfill", StepKind.add_tenant_id, name, n.table, "tenant_id", Safety.backfill,
                  f"multi-tenancy enabled: existing rows of {name} have no tenant",
                  strategy=f"add tenant_id nullable; UPDATE {_q(n.table)} SET tenant_id = <owning tenant id>; then SET NOT NULL and index it",
                  action="decide which tenant owns the existing rows",
                  sql=f"ALTER TABLE {_q(n.table)} ADD COLUMN tenant_id uuid;\nUPDATE {_q(n.table)} SET tenant_id = <tenant id>;\nALTER TABLE {_q(n.table)} ALTER COLUMN tenant_id SET NOT NULL")
        elif old.multi_tenant and not sn.multi_tenant:
            b.add("destructive", StepKind.drop_tenant_id, name, n.table, "tenant_id", Safety.destructive,
                  f"multi-tenancy disabled: tenant separation of {name} is lost",
                  action="make sure the data of all tenants may live together, then confirm",
                  sql=f"ALTER TABLE {_q(n.table)} DROP COLUMN tenant_id")

    _diff_relations(b, old, sn, replaced)
    steps = b.steps()
    schema_equal = _schema_sig(old) == _schema_sig(sn) and not steps
    ignored = _ignored(o_spec, n_spec, schema_equal=bool(steps) or schema_equal)
    return MigrationPlan(steps=steps, ignored_sections=ignored)
