"""Regression tests for create_blog.py (F-0397..F-0401)."""
import runpy
import uuid
from pathlib import Path

import httpx

SCRIPT = str(Path(__file__).resolve().parents[2] / "create_blog.py")


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.text = str(self._body)

    def json(self):
        return self._body


def _fake_client_factory(calls, fail_path=None, kwargs_sink=None):
    class FakeClient:
        def __init__(self, *a, **kw):
            if kwargs_sink is not None:
                kwargs_sink.update(kw)

        def _do(self, method, path, json=None):
            calls.append((method, path, json))
            if fail_path and path.endswith(fail_path):
                return _Resp(422, {"detail": "bad"})
            if method == "DELETE":
                return _Resp(204)
            body = {"id": str(uuid.uuid4()), "name": (json or {}).get("name", "x"), "valid": True, "issues": []}
            return _Resp(200, body)

        def post(self, path, json=None):
            return self._do("POST", path, json)

        def patch(self, path, json=None):
            return self._do("PATCH", path, json)

        def delete(self, path):
            return self._do("DELETE", path)

    return FakeClient


def _run(monkeypatch, fail_path=None, token="tok"):
    calls, kw = [], {}
    if token:
        monkeypatch.setenv("BUILDER_TOKEN", token)
    else:
        monkeypatch.delenv("BUILDER_TOKEN", raising=False)
    monkeypatch.setattr(httpx, "Client", _fake_client_factory(calls, fail_path, kw))
    try:
        runpy.run_path(SCRIPT)
    except SystemExit:
        pass
    return calls, kw


def _perms(calls):
    entity_ids = {}
    for m, p, j in calls:
        if m == "POST" and p.endswith("/entities"):
            entity_ids[len(entity_ids)] = None
    body = next(j for m, p, j in calls if p.endswith("/permissions"))
    return body["permissions"]


def test_sends_bearer_token(monkeypatch):
    _, kw = _run(monkeypatch)
    assert kw.get("headers", {}).get("Authorization") == "Bearer tok"


def test_missing_token_fails_before_any_request(monkeypatch):
    calls, _ = _run(monkeypatch, token=None)
    assert calls == []


def test_comment_reads_not_public_and_taxonomy_admin_only(monkeypatch):
    calls, _ = _run(monkeypatch)
    perms = _perms(calls)
    ents = [j for m, p, j in calls if m == "POST" and p.endswith("/entities")]
    assert len(ents) == 4
    ids = [p["entity_id"] for p in perms]
    order = list(dict.fromkeys(ids))
    by = {name: [p for p in perms if p["entity_id"] == eid] for name, eid in zip(["Category", "Tag", "Post", "Comment"], order)}
    for p in by["Comment"]:
        if p["operation"] in ("list", "get", "head"):
            assert p["roles"] == ["admin"]
    for n in ("Category", "Tag"):
        for p in by[n]:
            if p["operation"] in ("create", "update", "replace"):
                assert p["roles"] == ["admin"]
    for n in ("Post", "Comment"):
        for p in by[n]:
            if p["operation"] in ("update", "replace"):
                assert "author" in p["roles"] and p["row_rule"] == "role_scoped"
    assert "reader" in next(p for p in by["Comment"] if p["operation"] == "create")["roles"]


def test_author_not_self_assignable(monkeypatch):
    calls, _ = _run(monkeypatch)
    role = next(j for m, p, j in calls if p.endswith("/roles") and j["name"] == "author")
    assert role["self_assignable"] is False


def test_failure_cleans_up_project(monkeypatch):
    calls, _ = _run(monkeypatch, fail_path="/auth")
    assert any(m == "DELETE" and p.startswith("/projects/") for m, p, _ in calls)
