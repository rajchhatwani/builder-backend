from collections.abc import Callable
from typing import Any

import pytest

from app.core.spec_models import Spec
from app.core.validation import ValidationIssue, validate


def blog_spec() -> dict[str, Any]:
    return {
        "project": {"name": "Blog", "slug": "blog"},
        "entities": [
            {
                "name": "User",
                "table_name": "users",
                "plural_path": "users",
                "fields": [
                    {"name": "email", "type": "string", "required": True, "max_length": 255},
                    {"name": "role", "type": "enum", "enum_values": ["admin", "member"]},
                ],
            },
            {
                "name": "Post",
                "table_name": "posts",
                "plural_path": "posts",
                "options": {"filterable": ["title"], "sortable": ["created_at"]},
                "fields": [
                    {"name": "title", "type": "string", "max_length": 200},
                    {"name": "body", "type": "text"},
                ],
            },
            {"name": "Tag", "table_name": "tags", "plural_path": "tags", "fields": []},
        ],
        "relations": [
            {
                "kind": "one_to_many",
                "from_entity": "User",
                "to_entity": "Post",
                "from_name": "posts",
                "to_name": "author",
                "on_delete": "cascade",
                "required": True,
            },
            {
                "kind": "many_to_many",
                "from_entity": "Post",
                "to_entity": "Tag",
                "from_name": "tags",
                "to_name": "posts",
            },
        ],
    }


def issues_for(mutate: Callable[[dict[str, Any]], None]) -> list[ValidationIssue]:
    data = blog_spec()
    mutate(data)
    return validate(Spec.model_validate(data))


def codes(issues: list[ValidationIssue]) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in issues}


def test_valid_spec_has_no_issues() -> None:
    assert validate(Spec.model_validate(blog_spec())) == []


def test_all_issues_are_reported_not_just_the_first() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][0]["name"] = "bad name"
        d["entities"][1]["fields"][0]["name"] = "class"
        d["relations"][0]["to_entity"] = "Nope"

    found = codes(issues_for(mutate))
    assert ("entities[0].name", "invalid_identifier") in found
    assert ("entities[1].fields[0].name", "reserved_word") in found
    assert ("relations[0].to_entity", "unknown_entity") in found


# --- identifiers ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        'x"; import os',
        "x'; DROP TABLE users; --",
        "a b",
        "a-b",
        "../etc/passwd",
        "a\nb",
        "Name",
        "1abc",
        "",
        "é",
    ],
)
def test_field_name_injection_attempts_are_rejected(bad: str) -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][1]["fields"][0]["name"] = bad

    assert ("entities[1].fields[0].name", "invalid_identifier") in codes(issues_for(mutate))


@pytest.mark.parametrize(
    "bad", ['Post"; import os', "Post\n", "post", "Post_X", "Post-X", "../Post"]
)
def test_entity_name_must_be_pascal_case_identifier(bad: str) -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][1]["name"] = bad
        d["relations"] = []

    assert ("entities[1].name", "invalid_identifier") in codes(issues_for(mutate))


@pytest.mark.parametrize("key", ["table_name", "plural_path"])
@pytest.mark.parametrize("bad", ['x"; import os', "../x", "x y", "X", "x\n"])
def test_table_name_and_plural_path_injection_attempts_are_rejected(key: str, bad: str) -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][1][key] = bad
        d["relations"] = []

    assert (f"entities[1].{key}", "invalid_identifier") in codes(issues_for(mutate))


@pytest.mark.parametrize("bad", ['blog"; rm -rf /', "../blog", "Blog", "a b", "a\n", "-a"])
def test_slug_is_validated(bad: str) -> None:
    found = codes(issues_for(lambda d: d["project"].update(slug=bad)))
    assert ("project.slug", "invalid_identifier") in found


def test_project_name_rejects_control_characters() -> None:
    found = codes(issues_for(lambda d: d["project"].update(name='Blog"\nimport os')))
    assert ("project.name", "invalid_name") in found


def test_identifier_length_limit() -> None:
    found = codes(issues_for(lambda d: d["entities"][1]["fields"][0].update(name="a" * 64)))
    assert ("entities[1].fields[0].name", "identifier_too_long") in found


@pytest.mark.parametrize("word", ["class", "import", "lambda", "type", "list", "print", "match"])
def test_python_keywords_and_builtins_rejected_for_fields(word: str) -> None:
    found = codes(issues_for(lambda d: d["entities"][1]["fields"][0].update(name=word)))
    assert ("entities[1].fields[0].name", "reserved_word") in found


@pytest.mark.parametrize("word", ["order", "user", "group", "select", "table", "offset"])
def test_sql_reserved_words_rejected_for_fields_and_tables(word: str) -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][1]["fields"][0]["name"] = word
        d["entities"][2]["table_name"] = word

    found = codes(issues_for(mutate))
    assert ("entities[1].fields[0].name", "reserved_word") in found
    assert ("entities[2].table_name", "reserved_word") in found


def test_python_builtin_as_entity_name_rejected() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][2]["name"] = "Exception"

    assert ("entities[2].name", "reserved_word") in codes(issues_for(mutate))


def test_plural_path_cannot_shadow_health_endpoints() -> None:
    found = codes(issues_for(lambda d: d["entities"][2].update(plural_path="health")))
    assert ("entities[2].plural_path", "reserved_word") in found


def test_alembic_version_table_name_rejected() -> None:
    found = codes(issues_for(lambda d: d["entities"][2].update(table_name="alembic_version")))
    assert ("entities[2].table_name", "reserved_word") in found


@pytest.mark.parametrize("auto", ["id", "created_at", "updated_at"])
def test_auto_fields_cannot_be_redefined(auto: str) -> None:
    found = codes(issues_for(lambda d: d["entities"][1]["fields"][0].update(name=auto)))
    assert ("entities[1].fields[0].name", "reserved_name") in found


def test_deleted_at_reserved_only_with_soft_delete() -> None:
    def plain(d: dict[str, Any]) -> None:
        d["entities"][1]["fields"][0]["name"] = "deleted_at"
        d["entities"][1]["fields"][0]["type"] = "datetime"
        d["entities"][1]["fields"][0].pop("max_length")
        d["entities"][1]["options"] = {}

    assert issues_for(plain) == []

    def soft(d: dict[str, Any]) -> None:
        plain(d)
        d["entities"][1]["options"]["soft_delete"] = True

    assert ("entities[1].fields[0].name", "reserved_name") in codes(issues_for(soft))


# --- uniqueness -------------------------------------------------------------------------


def test_duplicate_entity_name_table_and_path() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][2].update(name="Post", table_name="posts", plural_path="posts")

    found = codes(issues_for(mutate))
    assert ("entities[2].name", "duplicate_name") in found
    assert ("entities[2].table_name", "duplicate_name") in found
    assert ("entities[2].plural_path", "duplicate_name") in found


def test_generated_class_names_must_not_collide() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][2].update(name="PostCreate", table_name="post_creates", plural_path="pcs")
        d["relations"] = []

    assert ("entities[2].name", "duplicate_name") in codes(issues_for(mutate))


def test_duplicate_field_name() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][1]["fields"].append({"name": "title", "type": "text"})

    assert ("entities[1].fields[2].name", "duplicate_name") in codes(issues_for(mutate))


def test_same_field_name_on_different_entities_is_fine() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][2]["fields"].append({"name": "title", "type": "text"})

    assert issues_for(mutate) == []


def test_relation_name_collides_with_field() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["relations"][0]["from_name"] = "email"

    assert ("relations[0].from_name", "duplicate_name") in codes(issues_for(mutate))


def test_relation_fk_column_collides_with_field() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][1]["fields"].append({"name": "author_id", "type": "uuid"})

    assert ("relations[0].to_name", "duplicate_name") in codes(issues_for(mutate))


def test_two_relations_with_same_names_on_one_entity_collide() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["relations"].append(dict(d["relations"][0]))

    found = codes(issues_for(mutate))
    assert ("relations[2].from_name", "duplicate_name") in found
    assert ("relations[2].to_name", "duplicate_name") in found


def test_relation_cannot_use_auto_field_name() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["relations"][1]["to_name"] = "created_at"

    assert ("relations[1].to_name", "reserved_name") in codes(issues_for(mutate))


def test_join_table_collision_with_entity_table() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][2]["table_name"] = "posts_tags"

    assert ("relations[1]", "duplicate_name") in codes(issues_for(mutate))


def test_two_many_to_many_relations_get_distinct_join_tables() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["relations"].append(
            {
                "kind": "many_to_many",
                "from_entity": "Post",
                "to_entity": "Tag",
                "from_name": "featured_tags",
                "to_name": "featured_posts",
            }
        )

    assert issues_for(mutate) == []


# --- relations --------------------------------------------------------------------------


def test_relation_targets_must_exist() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["relations"][0]["from_entity"] = "Ghost"
        d["relations"][1]["to_entity"] = 'x"; import os'

    found = codes(issues_for(mutate))
    assert ("relations[0].from_entity", "unknown_entity") in found
    assert ("relations[1].to_entity", "unknown_entity") in found


def test_unknown_relation_kind_and_on_delete() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["relations"][0]["kind"] = "many_to_one"
        d["relations"][1]["on_delete"] = "explode"

    found = codes(issues_for(mutate))
    assert ("relations[0].kind", "unknown_kind") in found
    assert ("relations[1].on_delete", "unknown_on_delete") in found


def test_required_relation_cannot_set_null() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["relations"][0]["on_delete"] = "set_null"

    assert ("relations[0]", "incompatible_on_delete") in codes(issues_for(mutate))


def test_many_to_many_cannot_set_null() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["relations"][1]["on_delete"] = "set_null"

    assert ("relations[1]", "incompatible_on_delete") in codes(issues_for(mutate))


def test_self_referential_relation_with_distinct_names_is_valid() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["relations"].append(
            {
                "kind": "one_to_many",
                "from_entity": "Tag",
                "to_entity": "Tag",
                "from_name": "children",
                "to_name": "parent",
            }
        )

    assert issues_for(mutate) == []


def test_self_referential_relation_with_same_names_collides() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["relations"].append(
            {
                "kind": "one_to_many",
                "from_entity": "Tag",
                "to_entity": "Tag",
                "from_name": "related",
                "to_name": "related",
            }
        )

    assert ("relations[2].to_name", "duplicate_name") in codes(issues_for(mutate))


# --- field definitions ------------------------------------------------------------------


def test_unknown_field_type() -> None:
    found = codes(issues_for(lambda d: d["entities"][1]["fields"][0].update(type="varchar")))
    assert ("entities[1].fields[0].type", "unknown_type") in found


def test_enum_needs_values() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][0]["fields"][1]["enum_values"] = []

    assert ("entities[0].fields[1].enum_values", "enum_empty") in codes(issues_for(mutate))


def test_enum_values_must_be_safe_and_unique() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][0]["fields"][1]["enum_values"] = ['a"; import os', "ok", "ok"]

    found = codes(issues_for(mutate))
    assert ("entities[0].fields[1].enum_values[0]", "invalid_identifier") in found
    assert ("entities[0].fields[1].enum_values", "duplicate_name") in found


def test_enum_values_only_on_enum_fields() -> None:
    found = codes(issues_for(lambda d: d["entities"][1]["fields"][0].update(enum_values=["a"])))
    assert ("entities[1].fields[0].enum_values", "unsupported_option") in found


def test_max_length_only_on_strings_and_in_range() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][1]["fields"][1]["max_length"] = 10
        d["entities"][1]["fields"][0]["max_length"] = 10**9

    found = codes(issues_for(mutate))
    assert ("entities[1].fields[1].max_length", "unsupported_option") in found
    assert ("entities[1].fields[0].max_length", "out_of_range") in found


def test_min_max_only_on_numeric_types_and_ordered() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][1]["fields"][0].update(min_value=1)
        d["entities"][1]["fields"].append(
            {"name": "views", "type": "integer", "min_value": 10, "max_value": 1}
        )

    found = codes(issues_for(mutate))
    assert ("entities[1].fields[0]", "unsupported_option") in found
    assert ("entities[1].fields[2]", "invalid_range") in found


def test_json_fields_cannot_be_unique_or_indexed() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][1]["fields"].append({"name": "meta", "type": "json", "unique": True})

    assert ("entities[1].fields[2]", "unsupported_option") in codes(issues_for(mutate))


@pytest.mark.parametrize(
    ("ftype", "extra", "default"),
    [
        ("string", {}, 5),
        ("string", {"max_length": 3}, "toolong"),
        ("text", {}, True),
        ("integer", {}, "1"),
        ("integer", {}, True),
        ("integer", {}, 1.5),
        ("integer", {}, 2**31),
        ("bigint", {}, 2**63),
        ("float", {}, "x"),
        ("decimal", {}, False),
        ("integer", {"min_value": 5}, 1),
        ("integer", {"max_value": 5}, 9),
        ("boolean", {}, "true"),
        ("boolean", {}, 1),
        ("date", {}, "not-a-date"),
        ("date", {}, 20260101),
        ("datetime", {}, "yesterday"),
        ("uuid", {}, "1234"),
        ("enum", {"enum_values": ["a", "b"]}, "c"),
    ],
)
def test_defaults_must_match_field_type(ftype: str, extra: dict[str, Any], default: Any) -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][2]["fields"].append({"name": "f", "type": ftype, "default": default, **extra})

    assert ("entities[2].fields[0].default", "invalid_default") in codes(issues_for(mutate))


@pytest.mark.parametrize(
    ("ftype", "extra", "default"),
    [
        ("string", {"max_length": 3}, "abc"),
        ("text", {}, "hello"),
        ("integer", {"min_value": 0, "max_value": 10}, 5),
        ("bigint", {}, 2**40),
        ("float", {}, 1),
        ("decimal", {}, 1.25),
        ("boolean", {}, False),
        ("date", {}, "2026-01-31"),
        ("datetime", {}, "2026-01-31T10:00:00+00:00"),
        ("uuid", {}, "6f1f0e1c-2d33-4a43-9a2e-7b1f6f1f0e1c"),
        ("json", {}, {"a": [1, 2]}),
        ("enum", {"enum_values": ["a", "b"]}, "a"),
    ],
)
def test_valid_defaults_are_accepted(ftype: str, extra: dict[str, Any], default: Any) -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][2]["fields"].append({"name": "f", "type": ftype, "default": default, **extra})

    assert issues_for(mutate) == []


# --- entity options ---------------------------------------------------------------------


def test_filter_sort_search_fields_must_exist() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][1]["options"] = {
            "filterable": ["ghost"],
            "sortable": ["ghost"],
            "searchable": ["ghost"],
        }

    found = codes(issues_for(mutate))
    for key in ("filterable", "sortable", "searchable"):
        assert (f"entities[1].options.{key}[0]", "unknown_field") in found


def test_option_fields_must_have_compatible_types() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][1]["fields"].append({"name": "meta", "type": "json"})
        d["entities"][1]["fields"].append({"name": "views", "type": "integer"})
        d["entities"][1]["options"] = {
            "filterable": ["meta"],
            "sortable": ["meta"],
            "searchable": ["views"],
        }

    found = codes(issues_for(mutate))
    assert ("entities[1].options.filterable[0]", "incompatible_type") in found
    assert ("entities[1].options.sortable[0]", "incompatible_type") in found
    assert ("entities[1].options.searchable[0]", "incompatible_type") in found


def test_auto_fields_can_be_sorted_and_filtered() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][1]["options"] = {"filterable": ["id"], "sortable": ["updated_at"]}

    assert issues_for(mutate) == []


def test_unknown_operation() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][1]["options"] = {"operations": ["list", "drop"]}

    assert ("entities[1].options.operations[1]", "unknown_operation") in codes(issues_for(mutate))


def test_page_sizes() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][1]["options"] = {"default_page_size": 50, "max_page_size": 10}
        d["entities"][2]["options"] = {"max_page_size": 5000}

    found = codes(issues_for(mutate))
    assert ("entities[1].options.default_page_size", "out_of_range") in found
    assert ("entities[2].options.max_page_size", "out_of_range") in found


# --- sizes and reserved sections --------------------------------------------------------


def test_entity_and_field_caps() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"] = [
            {"name": f"E{i}", "table_name": f"e{i}", "plural_path": f"e{i}", "fields": []}
            for i in range(101)
        ]
        d["entities"][0]["fields"] = [{"name": f"f{i}", "type": "text"} for i in range(101)]
        d["relations"] = []

    found = codes(issues_for(mutate))
    assert ("entities", "too_many") in found
    assert ("entities[0].fields", "too_many") in found


def test_project_description_length_and_engine() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["project"]["description"] = "x" * 2001
        d["project"]["db_engine"] = "mysql"

    found = codes(issues_for(mutate))
    assert ("project.description", "too_long") in found
    assert ("project.db_engine", "unsupported_value") in found


def test_spec_version_and_reserved_sections() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["spec_version"] = 2
        d["features"] = ["auth"]
        d["auth"] = {"provider": "keycloak"}

    found = codes(issues_for(mutate))
    assert ("spec_version", "unsupported_spec_version") in found
    assert ("features", "unsupported_feature") in found
    assert ("auth", "unsupported_feature") in found


# --- generator-safety rules -------------------------------------------------------------


@pytest.mark.parametrize("name", ["metadata", "registry", "copy", "json", "schema", "model_x"])
def test_attribute_names_that_clash_with_generated_bases_are_rejected(name: str) -> None:
    found = codes(issues_for(lambda d: d["entities"][1]["fields"][0].update(name=name)))
    assert ("entities[1].fields[0].name", "reserved_word") in found


def test_relation_names_get_the_same_attribute_check() -> None:
    found = codes(issues_for(lambda d: d["relations"][0].update(from_name="metadata")))
    assert ("relations[0].from_name", "reserved_word") in found


@pytest.mark.parametrize("name", ["limit", "offset", "sort", "q"])
def test_list_query_parameter_names_cannot_be_filterable(name: str) -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][1]["fields"].append({"name": name, "type": "string"})
        d["entities"][1]["options"] = {"filterable": [name]}

    assert ("entities[1].options.filterable[0]", "reserved_word") in codes(issues_for(mutate))


def test_entity_named_like_a_repository_suffix_collides() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][2].update(
            name="PostRepository", table_name="post_repos", plural_path="post_repos"
        )
        d["relations"] = []

    assert ("entities[2].name", "duplicate_name") in codes(issues_for(mutate))


def test_json_default_must_be_finite_json() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["entities"][2]["fields"].append(
            {"name": "meta", "type": "json", "default": {"x": float("nan")}}
        )

    assert ("entities[2].fields[0].default", "invalid_default") in codes(issues_for(mutate))


def test_required_relations_that_form_a_cycle_are_rejected() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["relations"].append(
            {
                "kind": "one_to_many",
                "from_entity": "Post",
                "to_entity": "User",
                "from_name": "authored",
                "to_name": "first_post",
                "required": True,
            }
        )

    found = codes(issues_for(mutate))
    assert ("relations[0]", "required_cycle") in found
    assert ("relations[2]", "required_cycle") in found


def test_required_self_relation_is_a_cycle_but_optional_one_is_fine() -> None:
    def self_relation(required: bool) -> Callable[[dict[str, Any]], None]:
        def mutate(d: dict[str, Any]) -> None:
            d["relations"].append(
                {
                    "kind": "one_to_many",
                    "from_entity": "Tag",
                    "to_entity": "Tag",
                    "from_name": "children",
                    "to_name": "parent",
                    "required": required,
                }
            )

        return mutate

    assert ("relations[2]", "required_cycle") in codes(issues_for(self_relation(True)))
    assert issues_for(self_relation(False)) == []
