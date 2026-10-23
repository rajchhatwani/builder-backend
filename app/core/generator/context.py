"""Turns a validated Spec into the template-ready `ProjectCtx` shared by all feature modules.

Everything that ends up as Python source is built here, from validated identifiers and
`repr()` of scalar values; templates only arrange these pieces. Lists are sorted so output
never depends on dict or set ordering.
"""

import math
from dataclasses import dataclass, field, replace
from typing import Any

from app.core import naming
from app.core.enums import OnDelete, RelationKind, RowRule
from app.core.spec_models import Spec, SpecAuth, SpecEntity, SpecField, SpecRelation

_ON_DELETE_SQL = {
    OnDelete.cascade: "CASCADE",
    OnDelete.set_null: "SET NULL",
    OnDelete.restrict: "RESTRICT",
}
_STRING_FALLBACK_LENGTH = 255
_ENUM_COLUMN_LENGTH = 64
_PATCHABLE = {"string", "text", "integer", "bigint", "float", "boolean", "enum"}
_FILTER_TYPES = {
    "string": "str",
    "text": "str",
    "enum": "str",
    "integer": "int",
    "bigint": "int",
    "float": "float",
    "decimal": "_decimal.Decimal",
    "boolean": "bool",
    "date": "_dt.date",
    "datetime": "_dt.datetime",
    "uuid": "_uuid.UUID",
}


@dataclass(frozen=True)
class FieldCtx:
    name: str
    type: str
    required: bool
    unique: bool
    column: str  # full model column declaration
    migration_column: str  # sa.Column(...) line for the initial migration
    create_decl: str
    update_decl: str
    read_decl: str
    sample: str  # python expression producing a valid JSON value, used in tests
    patchable: bool
    filter_type: str | None  # python type for a query parameter, None if not filterable


@dataclass(frozen=True)
class FkCtx:
    """Foreign key column on the `to` entity of a one_to_many / one_to_one relation."""

    column: str
    target_entity: str
    target_table: str
    target_module: str
    on_delete: str
    required: bool
    unique: bool
    constraint_name: str
    attr: str  # relationship attribute on this entity (the relation's to_name)
    back_attr: str  # relationship attribute on the target entity (from_name)
    target_is_self: bool
    column_decl: str
    create_decl: str
    update_decl: str
    read_decl: str
    relationship_decl: str


@dataclass(frozen=True)
class RelationAttrCtx:
    """A relationship attribute that appears on read (and, for many_to_many, on write)."""

    attr: str
    target_entity: str
    target_module: str
    scalar: bool  # one_to_one from-side
    many_to_many: bool
    relationship_decl: str
    create_decl: str = ""
    update_decl: str = ""
    read_decl: str = ""


@dataclass(frozen=True)
class AccessCtx:
    """Who may call one operation of an entity, and which rows they get to see.

    Rendered into the router as `access_dependency(...)`; see app/auth/access.py in the
    generated project. Everything here is a validated identifier or a pyrepr literal."""

    op: str
    roles: tuple[str, ...] = ()  # any one of these roles; empty = no role needed
    owner: bool = False  # only rows the user created
    admin_sees_all: bool = False  # ...unless the user is an admin (role_scoped)
    match: tuple[str, str] | None = None  # (column, python literal) for custom_filter
    stamp: bool = False  # record the user as created_by_id on create
    authenticate: bool = False  # a signed-in user is required even without roles
    tenant: bool = False  # only rows of the caller's tenant (and stamp it on create)

    @property
    def needs_user(self) -> bool:
        return bool(self.roles or self.owner or self.stamp or self.authenticate or self.tenant)

    @property
    def call(self) -> str:
        args: list[str] = []
        if self.roles:
            args.append(f"roles={tuple_literal(self.roles)}")
        if self.owner:
            args.append("owner=True")
        if self.admin_sees_all:
            args.append("admin_sees_all=True")
        if self.match is not None:
            args.append(f"match=({self.match[0]!r}, {self.match[1]})")
        if self.stamp:
            args.append("stamp=True")
        if self.authenticate:
            args.append("authenticate=True")
        if self.tenant:
            args.append("tenant=True")
        return f"access_dependency({', '.join(args)})"


@dataclass(frozen=True)
class EntityCtx:
    name: str
    table: str
    path: str
    ops: frozenset[str]
    soft_delete: bool
    default_page_size: int
    max_page_size: int
    fields: tuple[FieldCtx, ...]
    fks: tuple[FkCtx, ...]
    attrs: tuple[RelationAttrCtx, ...]  # collections, one_to_one from-side, many_to_many
    filterable: tuple[tuple[str, str], ...]  # (name, python type)
    sortable: tuple[str, ...]
    searchable: tuple[str, ...]
    # names of Pydantic fields that may never be null on update
    non_nullable: tuple[str, ...] = ()
    # modules (table names) of other entities referenced by relationships, excluding self
    related_modules: tuple[tuple[str, str], ...] = ()  # (module, class name)
    reference_targets: tuple[tuple[str, str, str], ...] = ()  # (payload key, class, module)
    many_to_many_targets: tuple[tuple[str, str, str], ...] = ()
    eager: tuple[str, ...] = ()
    required_fks: tuple[FkCtx, ...] = ()
    migration_columns: tuple[str, ...] = ()
    unique_constraints: tuple[tuple[str, str], ...] = ()  # (constraint name, column)
    indexes: tuple[tuple[str, str], ...] = ()  # (index name, column)
    access: tuple[AccessCtx, ...] = ()  # operations that need a signed-in user or row scoping
    owned: bool = False  # rows record who created them (created_by_id)
    tenant_scoped: bool = False  # rows belong to a tenant (tenant_id)

    @property
    def access_ops(self) -> frozenset[str]:
        return frozenset(a.op for a in self.access)

    @property
    def repo_imports(self) -> tuple[tuple[str, str], ...]:
        """(module, class) of every model the repository module must import, sorted."""
        pairs = {(self.table, self.name)}
        pairs |= {(module, cls) for _key, cls, module in self.reference_targets}
        pairs |= {(module, cls) for _key, cls, module in self.many_to_many_targets}
        return tuple(sorted(pairs))

    @property
    def schema_imports(self) -> tuple[str, ...]:
        """Schema classes the router uses, in isort order."""
        names: list[str] = []
        if self.ops & {"create", "replace"}:
            names.append(f"{self.name}Create")
        if self.ops & {"list", "get", "create", "replace", "update"}:
            names.append(f"{self.name}Read")
        if "update" in self.ops:
            names.append(f"{self.name}Update")
        return tuple(names)

    @property
    def filterable_names(self) -> tuple[str, ...]:
        return tuple(name for name, _type in self.filterable)

    @property
    def references_literal(self) -> str:
        return _dict_literal((key, cls) for key, cls, _module in self.reference_targets)

    @property
    def many_to_many_literal(self) -> str:
        return _dict_literal((key, cls) for key, cls, _module in self.many_to_many_targets)


@dataclass(frozen=True)
class JoinTableCtx:
    name: str
    left_table: str
    right_table: str
    on_delete: str
    left_constraint: str
    right_constraint: str
    pk_name: str


@dataclass(frozen=True)
class ProjectCtx:
    spec: Spec
    name: str
    slug: str
    description: str | None
    entities: tuple[EntityCtx, ...]
    join_tables: tuple[JoinTableCtx, ...]
    tables: tuple[str, ...]  # every table incl. join tables, sorted
    entity_by_name: dict[str, EntityCtx] = field(default_factory=dict)

    @property
    def auth(self) -> SpecAuth | None:
        """The auth block when it is switched on, else None."""
        auth = self.spec.auth
        return auth if auth is not None and auth.enabled else None


def tuple_literal(items: Any) -> str:
    """("a", "b") / ("a",) / () from validated identifiers."""
    names = list(items)
    body = ", ".join(f'"{n}"' for n in names)
    return f"({body},)" if len(names) == 1 else f"({body})"


def _dict_literal(pairs: Any) -> str:
    """{"key": ClassName, ...}; keys and class names are validated identifiers."""
    return "{" + ", ".join(f'"{key}": {cls}' for key, cls in pairs) + "}"


# --- scalar helpers ---------------------------------------------------------------------


def _number(value: float) -> str:
    return repr(int(value)) if float(value).is_integer() else repr(float(value))


def py_type(f: SpecField) -> str:
    match f.type:
        case "string" | "text":
            return "str"
        case "integer" | "bigint":
            return "int"
        case "float":
            return "float"
        case "decimal":
            return "_decimal.Decimal"
        case "boolean":
            return "bool"
        case "date":
            return "_dt.date"
        case "datetime":
            return "_dt.datetime"
        case "uuid":
            return "_uuid.UUID"
        case "json":
            return "_t.Any"
        case "enum":
            values = ", ".join(repr(v) for v in f.enum_values or [])
            return f"_t.Literal[{values}]"
    raise ValueError(f"unknown field type {f.type}")


def sa_type(f: SpecField, sa: str = "_sa.", pg: str = "_pg.") -> str:
    match f.type:
        case "string":
            return f"{sa}String({f.max_length or _STRING_FALLBACK_LENGTH})"
        case "text":
            return f"{sa}Text()"
        case "integer":
            return f"{sa}Integer()"
        case "bigint":
            return f"{sa}BigInteger()"
        case "float":
            return f"{sa}Float()"
        case "decimal":
            return f"{sa}Numeric(18, 6)"
        case "boolean":
            return f"{sa}Boolean()"
        case "date":
            return f"{sa}Date()"
        case "datetime":
            return f"{sa}DateTime(timezone=True)"
        case "uuid":
            return f"{sa}Uuid()"
        case "json":
            return f"{pg}JSONB()"
        case "enum":
            return f"{sa}String({_ENUM_COLUMN_LENGTH})"
    raise ValueError(f"unknown field type {f.type}")


def default_expr(f: SpecField) -> str | None:
    """Python expression for the field's default, built only from repr() of scalars."""
    value: Any = f.default
    if value is None:
        return None
    match f.type:
        case "string" | "text" | "enum" | "boolean" | "json":
            return repr(value)
        case "integer" | "bigint":
            return repr(int(value))
        case "float":
            return repr(float(value))
        case "decimal":
            return f"_decimal.Decimal({str(value)!r})"
        case "date":
            return f"_dt.date.fromisoformat({str(value)!r})"
        case "datetime":
            return f"_dt.datetime.fromisoformat({str(value)!r})"
        case "uuid":
            return f"_uuid.UUID({str(value)!r})"
    raise ValueError(f"unknown field type {f.type}")


# What the database column can hold. Anything outside is rejected by the schema (422) so a
# value the column cannot store never reaches the database as a 500.
_INT_RANGE = {"integer": (-(2**31), 2**31 - 1), "bigint": (-(2**63), 2**63 - 1)}
_DECIMAL_DIGITS = 18  # Numeric(18, 6)
_DECIMAL_PLACES = 6


def _constraints(f: SpecField) -> list[str]:
    out: list[str] = []
    if f.type == "string":
        out.append(f"max_length={f.max_length or _STRING_FALLBACK_LENGTH}")
    if f.type in _INT_RANGE:
        low, high = _INT_RANGE[f.type]
        ge = f.min_value if f.min_value is not None and f.min_value > low else low
        le = f.max_value if f.max_value is not None and f.max_value < high else high
        out.append(f"ge={_number(ge)}")
        out.append(f"le={_number(le)}")
    elif f.type in ("float", "decimal"):
        if f.min_value is not None:
            out.append(f"ge={_number(f.min_value)}")
        if f.max_value is not None:
            out.append(f"le={_number(f.max_value)}")
    if f.type == "decimal":
        out.append(f"max_digits={_DECIMAL_DIGITS}")
        out.append(f"decimal_places={_DECIMAL_PLACES}")
    return out


def _sample(f: SpecField) -> str:
    match f.type:
        case "string":
            return f"_token({min(f.max_length or _STRING_FALLBACK_LENGTH, 12)})"
        case "text":
            return '"sample text " + _token(6)'
        case "integer" | "bigint":
            low = math.ceil(f.min_value) if f.min_value is not None else None
            high = math.floor(f.max_value) if f.max_value is not None else None
            if low is None:
                low = min(1, high) if high is not None else 1
            if high is None:
                high = low + 1000
            return f"_random.randint({low}, {max(low, high)})"
        case "float" | "decimal":
            low_f = f.min_value if f.min_value is not None else 0
            high_f = f.max_value if f.max_value is not None else low_f + 1000
            body = f"round(_random.uniform({_number(low_f)}, {_number(max(low_f, high_f))}), 2)"
            return body if f.type == "float" else f"str({body})"
        case "boolean":
            return "True"
        case "date":
            return (
                "(_dt.date(2026, 1, 1) + _dt.timedelta(days=_random.randint(0, 3000))).isoformat()"
            )
        case "datetime":
            return (
                "(_dt.datetime(2026, 1, 1, tzinfo=_dt.UTC)"
                " + _dt.timedelta(minutes=_random.randint(0, 99999))).isoformat()"
            )
        case "uuid":
            return "str(_uuid.uuid4())"
        case "json":
            return '{"key": "value"}'
        case "enum":
            return repr((f.enum_values or [""])[0])
    raise ValueError(f"unknown field type {f.type}")


def _field_ctx(f: SpecField, filterable: set[str]) -> FieldCtx:
    ann = py_type(f)
    nullable = not f.required
    default = default_expr(f)
    factory = f.type == "json"
    constraints = _constraints(f)

    # --- model column
    mapped = "str" if f.type == "enum" else ann
    if nullable and f.type != "json":
        mapped = f"{mapped} | None"
    args = [sa_type(f), f"nullable={nullable}"]
    if f.unique:
        args.append("unique=True")
    elif f.indexed:
        args.append("index=True")
    if default is not None:
        args.append(f"default=lambda: {default}" if factory else f"default={default}")
    column = f"{f.name}: _orm.Mapped[{mapped}] = _orm.mapped_column({', '.join(args)})"

    # --- migration column
    migration = f'sa.Column("{f.name}", {sa_type(f, "sa.", "postgresql.")}, nullable={nullable}),'

    # --- create schema
    create_ann = ann if f.required or f.type == "json" else f"{ann} | None"
    kwargs = list(constraints)
    if default is not None:
        kwargs.insert(0, f"default_factory=lambda: {default}" if factory else f"default={default}")
    elif nullable:
        kwargs.insert(0, "default=None")
    if kwargs:
        create_decl = f"{f.name}: {create_ann} = _pd.Field({', '.join(kwargs)})"
    else:
        create_decl = f"{f.name}: {create_ann}"

    # --- update schema: every field optional
    update_ann = ann if f.type == "json" else f"{ann} | None"
    update_decl = f"{f.name}: {update_ann} = _pd.Field({', '.join(['default=None', *constraints])})"

    read_ann = ann if (f.required or f.type == "json") else f"{ann} | None"
    return FieldCtx(
        name=f.name,
        type=f.type,
        required=f.required,
        unique=f.unique,
        column=column,
        migration_column=migration,
        create_decl=create_decl,
        update_decl=update_decl,
        read_decl=f"{f.name}: {read_ann}",
        sample=_sample(f),
        patchable=f.type in _PATCHABLE,
        filter_type=_FILTER_TYPES.get(f.type) if f.name in filterable else None,
    )


# --- relations --------------------------------------------------------------------------


def _fk_ctx(rel: SpecRelation, tables: dict[str, str], to_table: str) -> FkCtx:
    from_table = tables[rel.from_entity]
    column = naming.fk_column_name(rel.to_name)
    required = rel.required
    one_to_one = rel.kind == RelationKind.one_to_one
    self_ref = rel.from_entity == rel.to_entity
    ondelete = _ON_DELETE_SQL[OnDelete(rel.on_delete)]
    uuid_ann = "_uuid.UUID" if required else "_uuid.UUID | None"

    col_args = [
        f'_sa.ForeignKey("{from_table}.id", ondelete="{ondelete}")',
        f"nullable={not required}",
    ]
    col_args.append("unique=True" if one_to_one else "index=True")
    column_decl = f"{column}: _orm.Mapped[{uuid_ann}] = _orm.mapped_column({', '.join(col_args)})"

    rel_args = [
        repr(rel.from_entity),
        f"back_populates={rel.from_name!r}",
        f'foreign_keys="[{rel.to_entity}.{column}]"',
    ]
    if self_ref:
        rel_args.append(f'remote_side="[{rel.to_entity}.id]"')
    joined_args = ", ".join(rel_args)
    relationship_decl = (
        f'{rel.to_name}: _orm.Mapped["{rel.from_entity}"] = _orm.relationship({joined_args})'
    )

    create_decl = f"{column}: _uuid.UUID" if required else f"{column}: _uuid.UUID | None = None"
    return FkCtx(
        column=column,
        target_entity=rel.from_entity,
        target_table=from_table,
        target_module=from_table,
        on_delete=ondelete,
        required=required,
        unique=one_to_one,
        constraint_name=f"fk_{to_table}_{column}_{from_table}",
        attr=rel.to_name,
        back_attr=rel.from_name,
        target_is_self=self_ref,
        column_decl=column_decl,
        create_decl=create_decl,
        update_decl=f"{column}: _uuid.UUID | None = None",
        read_decl=f"{column}: {uuid_ann}",
        relationship_decl=relationship_decl,
    )


def _from_side_attr(rel: SpecRelation, tables: dict[str, str]) -> RelationAttrCtx:
    """Attribute on the `from` entity of a one_to_many / one_to_one relation."""
    column = naming.fk_column_name(rel.to_name)
    args = [
        repr(rel.to_entity),
        f"back_populates={rel.to_name!r}",
        f'foreign_keys="[{rel.to_entity}.{column}]"',
        "passive_deletes=True",
    ]
    scalar = rel.kind == RelationKind.one_to_one
    if scalar:
        args.append("uselist=False")
        annotation = f'_orm.Mapped["{rel.to_entity}"]'
        read = f"{rel.from_name}: _uuid.UUID | None = None"
    else:
        annotation = f'_orm.Mapped[list["{rel.to_entity}"]]'
        read = f"{rel.from_name}: list[_uuid.UUID] = _pd.Field(default_factory=list)"
    return RelationAttrCtx(
        attr=rel.from_name,
        target_entity=rel.to_entity,
        target_module=tables[rel.to_entity],
        scalar=scalar,
        many_to_many=False,
        relationship_decl=f"{rel.from_name}: {annotation} = _orm.relationship({', '.join(args)})",
        read_decl=read,
    )


def _m2m_attr(
    rel: SpecRelation, tables: dict[str, str], join: str, *, from_side: bool
) -> RelationAttrCtx:
    own, other = (rel.from_entity, rel.to_entity) if from_side else (rel.to_entity, rel.from_entity)
    attr, back = (rel.from_name, rel.to_name) if from_side else (rel.to_name, rel.from_name)
    own_col, other_col = ("left_id", "right_id") if from_side else ("right_id", "left_id")
    args = [
        repr(other),
        f"secondary={join!r}",
        f'primaryjoin="{own}.id == {join}.c.{own_col}"',
        f'secondaryjoin="{other}.id == {join}.c.{other_col}"',
        f"back_populates={back!r}",
        "passive_deletes=True",
    ]
    return RelationAttrCtx(
        attr=attr,
        target_entity=other,
        target_module=tables[other],
        scalar=False,
        many_to_many=True,
        relationship_decl=(
            f'{attr}: _orm.Mapped[list["{other}"]] = _orm.relationship({", ".join(args)})'
        ),
        create_decl=f"{attr}: list[_uuid.UUID] = _pd.Field(default_factory=list)",
        update_decl=f"{attr}: list[_uuid.UUID] | None = None",
        read_decl=f"{attr}: list[_uuid.UUID] = _pd.Field(default_factory=list)",
    )


# --- entities ---------------------------------------------------------------------------


def _build_entity(
    e: SpecEntity, relations: list[SpecRelation], tables: dict[str, str]
) -> EntityCtx:
    options = e.options
    table = e.table_name
    filterable_names = set(options.filterable)
    fields = tuple(_field_ctx(f, filterable_names) for f in e.fields)

    fks: list[FkCtx] = []
    attrs: list[RelationAttrCtx] = []
    for rel in relations:
        if rel.kind in (RelationKind.one_to_many, RelationKind.one_to_one):
            if rel.to_entity == e.name:
                fks.append(_fk_ctx(rel, tables, table))
            if rel.from_entity == e.name:
                attrs.append(_from_side_attr(rel, tables))
        else:
            join = naming.join_table_name(tables[rel.from_entity], rel.from_name)
            if rel.from_entity == e.name:
                attrs.append(_m2m_attr(rel, tables, join, from_side=True))
            if rel.to_entity == e.name:
                attrs.append(_m2m_attr(rel, tables, join, from_side=False))
    fks.sort(key=lambda fk: fk.column)
    attrs.sort(key=lambda a: a.attr)

    auto_types = dict(naming.AUTO_FIELDS)
    if options.soft_delete:
        auto_types[naming.SOFT_DELETE_FIELD[0]] = naming.SOFT_DELETE_FIELD[1]
    types = {**auto_types, **{f.name: f.type for f in e.fields}}
    auto_filter_types = {
        "id": "_uuid.UUID",
        "created_at": "_dt.datetime",
        "updated_at": "_dt.datetime",
        "deleted_at": "_dt.datetime",
    }

    filterable: list[tuple[str, str]] = []
    for name in sorted(filterable_names):
        filter_type = auto_filter_types.get(name) or _FILTER_TYPES[types[name]]
        filterable.append((name, filter_type))

    non_nullable = [f.name for f in fields if f.required]
    non_nullable += [fk.column for fk in fks if fk.required]

    related: dict[str, str] = {}
    for fk in fks:
        if not fk.target_is_self:
            related[fk.target_module] = fk.target_entity
    for a in attrs:
        if a.target_entity != e.name:
            related[a.target_module] = a.target_entity

    indexes = [(f"ix_{table}_{f.name}", f.name) for f in e.fields if f.indexed and not f.unique]
    indexes += [(f"ix_{table}_{fk.column}", fk.column) for fk in fks if not fk.unique]
    uniques = [(f"uq_{table}_{f.name}", f.name) for f in e.fields if f.unique]
    uniques += [(f"uq_{table}_{fk.column}", fk.column) for fk in fks if fk.unique]

    migration_columns = ['sa.Column("id", sa.Uuid(), nullable=False),']
    migration_columns += [f.migration_column for f in fields]
    for fk in fks:
        migration_columns.append(
            f'sa.Column("{fk.column}", sa.Uuid(), nullable={not fk.required}),'
        )
    migration_columns.append('sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),')
    migration_columns.append('sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),')
    if options.soft_delete:
        migration_columns.append(
            'sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),'
        )

    return EntityCtx(
        name=e.name,
        table=table,
        path=e.plural_path,
        ops=frozenset(options.operations),
        soft_delete=options.soft_delete,
        default_page_size=options.default_page_size,
        max_page_size=options.max_page_size,
        fields=fields,
        fks=tuple(fks),
        attrs=tuple(attrs),
        filterable=tuple(filterable),
        sortable=tuple(sorted(set(options.sortable))),
        searchable=tuple(sorted(set(options.searchable))),
        non_nullable=tuple(non_nullable) + tuple(a.attr for a in attrs if a.many_to_many),
        related_modules=tuple(sorted(related.items())),
        reference_targets=tuple((fk.column, fk.target_entity, fk.target_module) for fk in fks),
        many_to_many_targets=tuple(
            (a.attr, a.target_entity, a.target_module) for a in attrs if a.many_to_many
        ),
        eager=tuple(a.attr for a in attrs),
        required_fks=tuple(fk for fk in fks if fk.required),
        migration_columns=tuple(migration_columns),
        unique_constraints=tuple(sorted(uniques)),
        indexes=tuple(sorted(indexes)),
    )


def build_context(spec: Spec) -> ProjectCtx:
    entities_sorted = sorted(spec.entities, key=lambda e: e.table_name)
    tables = {e.name: e.table_name for e in entities_sorted}
    relations = sorted(spec.relations, key=lambda r: (r.from_entity, r.from_name, r.to_entity))
    entity_ctxs = tuple(_build_entity(e, relations, tables) for e in entities_sorted)

    joins: list[JoinTableCtx] = []
    for rel in relations:
        if rel.kind != RelationKind.many_to_many:
            continue
        name = naming.join_table_name(tables[rel.from_entity], rel.from_name)
        left, right = tables[rel.from_entity], tables[rel.to_entity]
        joins.append(
            JoinTableCtx(
                name=name,
                left_table=left,
                right_table=right,
                on_delete=_ON_DELETE_SQL[OnDelete(rel.on_delete)],
                left_constraint=f"fk_{name}_left_id_{left}",
                right_constraint=f"fk_{name}_right_id_{right}",
                pk_name=f"pk_{name}",
            )
        )
    joins.sort(key=lambda j: j.name)
    entity_ctxs = _attach_access(spec, entity_ctxs)
    all_tables = sorted({e.table for e in entity_ctxs} | {j.name for j in joins})
    return ProjectCtx(
        spec=spec,
        name=spec.project.name,
        slug=spec.project.slug,
        description=spec.project.description,
        entities=entity_ctxs,
        join_tables=tuple(joins),
        tables=tuple(all_tables),
        entity_by_name={e.name: e for e in entity_ctxs},
    )


# --- access control (auth permissions) --------------------------------------------------


def _filter_literal(field_type: str, value: str) -> str:
    """The custom_filter value as a Python literal of the column's type (already validated)."""
    match field_type:
        case "integer" | "bigint":
            return repr(int(value))
        case "boolean":
            return "True" if value == "true" else "False"
        case _:
            return repr(value)


def _attach_access(spec: Spec, entities: tuple[EntityCtx, ...]) -> tuple[EntityCtx, ...]:
    auth = spec.auth
    if auth is None or not auth.enabled or not auth.permissions:
        return entities
    spec_entities = {e.name: e for e in spec.entities}
    result: list[EntityCtx] = []
    for entity in entities:
        perms = {
            p.operation: p
            for p in auth.permissions
            if p.entity == entity.name and p.operation in entity.ops
        }
        owned = any(p.row_rule in (RowRule.owner, RowRule.role_scoped) for p in perms.values())
        # One tenant rule on any operation puts the whole entity inside the tenant: isolation
        # must not depend on every single operation remembering to opt in.
        tenant_scoped = auth.multi_tenant and any(
            p.row_rule == RowRule.tenant for p in perms.values()
        )
        access: list[AccessCtx] = []
        for op in sorted(entity.ops):
            perm = perms.get(op)
            rule = perm.row_rule if perm is not None else None
            is_create = op == "create"
            match = None
            if perm is not None and rule == RowRule.custom_filter:
                column = next(
                    f
                    for f in spec_entities[entity.name].fields
                    if f.name == perm.custom_filter_field
                )
                match = (column.name, _filter_literal(column.type, perm.custom_filter_value or ""))
            scoped_to_owner = rule in (RowRule.owner, RowRule.role_scoped) and not is_create
            ctx = AccessCtx(
                op=op,
                roles=tuple(sorted(perm.roles)) if perm is not None else (),
                owner=scoped_to_owner,
                admin_sees_all=rule == RowRule.role_scoped and not is_create,
                match=match if not is_create else None,
                stamp=owned and is_create,
                authenticate=scoped_to_owner or (owned and is_create) or tenant_scoped,
                tenant=tenant_scoped,
            )
            if ctx.needs_user or ctx.match is not None:
                access.append(ctx)  # anything else is a public slot: nothing to enforce
        # The smoke tests create rows from sample data, so a field that a custom_filter looks
        # at must get the value the filter lets through (or the test would never see its row).
        wanted = {a.match[0]: a.match[1] for a in reversed(access) if a.match is not None}
        fields = tuple(
            replace(f, sample=wanted[f.name]) if f.name in wanted else f for f in entity.fields
        )
        result.append(
            replace(
                entity,
                access=tuple(access),
                owned=owned,
                tenant_scoped=tenant_scoped,
                fields=fields,
            )
        )
    return tuple(result)
