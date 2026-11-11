[tool.ruff]
line-length = 100
target-version = "py312"
src = ["."]
extend-exclude = ["alembic/versions"]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B"]
ignore = ["E501"]

[tool.ruff.lint.isort]
# The local alembic/ directory would otherwise make ruff treat the library as first-party.
known-third-party = ["alembic"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"
pythonpath = ["."]
testpaths = ["tests"]
