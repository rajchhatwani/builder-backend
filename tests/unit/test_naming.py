from app.core.naming import pluralize, slugify, to_snake_case


def test_to_snake_case_converts_pascal_case() -> None:
    assert to_snake_case("Post") == "post"
    assert to_snake_case("BlogPost") == "blog_post"
    assert to_snake_case("UserID") == "user_i_d"


def test_pluralize_handles_common_suffixes() -> None:
    assert pluralize("post") == "posts"
    assert pluralize("tag") == "tags"
    assert pluralize("box") == "boxes"
    assert pluralize("category") == "categories"
    assert pluralize("key") == "keys"


def test_slugify_normalizes_name() -> None:
    assert slugify("My Blog") == "my-blog"
    assert slugify("  Weird__Name!! ") == "weird-name"
    assert slugify("") == "project"
