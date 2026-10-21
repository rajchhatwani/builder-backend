from enum import StrEnum


class DbEngine(StrEnum):
    postgres = "postgres"


class FieldType(StrEnum):
    string = "string"
    text = "text"
    integer = "integer"
    bigint = "bigint"
    float = "float"
    decimal = "decimal"
    boolean = "boolean"
    date = "date"
    datetime = "datetime"
    uuid = "uuid"
    json = "json"
    enum = "enum"


class RelationKind(StrEnum):
    one_to_many = "one_to_many"
    many_to_many = "many_to_many"
    one_to_one = "one_to_one"


class OnDelete(StrEnum):
    cascade = "cascade"
    set_null = "set_null"
    restrict = "restrict"
