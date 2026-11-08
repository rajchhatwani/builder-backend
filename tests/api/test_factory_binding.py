"""R-001 guard: add_to_project_org() must use the database of the running test."""

from tests.api.conftest import _FACTORY


def test_helper_factory_is_this_tests_factory(session_factory) -> None:  # noqa: ANN001
    assert _FACTORY and _FACTORY[0] is session_factory
