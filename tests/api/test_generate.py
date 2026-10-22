"""M4 acceptance: preview, download (in-memory zip) and the generations history."""

import io
import zipfile

from httpx import AsyncClient

from app.core.generator import generate
from app.core.spec_models import Spec, spec_hash
from tests.api.test_spec import build_blog

MISSING = "00000000-0000-0000-0000-000000000000"


async def test_preview_lists_files_without_recording_history(client: AsyncClient) -> None:
    project_id = await build_blog(client)
    spec = Spec.model_validate((await client.get(f"/projects/{project_id}/spec")).json())

    response = await client.post(f"/projects/{project_id}/generate/preview")

    assert response.status_code == 200, response.text
    body = response.json()
    paths = [f["path"] for f in body["files"]]
    assert paths == sorted(paths)
    assert {"app/main.py", "alembic/versions/0001_initial.py", "docker-compose.yml"} <= set(paths)
    assert "tests/test_posts.py" in paths
    assert body["total_files"] == len(paths)
    assert body["total_size"] == sum(f["size"] for f in body["files"])
    assert body["spec_hash"] == spec_hash(spec)
    history = (await client.get(f"/projects/{project_id}/generations")).json()
    assert history["total"] == 0


async def test_download_returns_a_zip_of_the_generated_project(client: AsyncClient) -> None:
    project_id = await build_blog(client)
    spec = Spec.model_validate((await client.get(f"/projects/{project_id}/spec")).json())

    response = await client.get(f"/projects/{project_id}/generate/download")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"] == 'attachment; filename="blog.zip"'
    assert response.headers["x-spec-hash"] == spec_hash(spec)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert names == sorted(names)
        assert all(n.startswith("blog/") for n in names)
        expected = generate(spec)
        assert [n.removeprefix("blog/") for n in names] == list(expected)
        assert archive.read("blog/app/main.py").decode() == expected["app/main.py"]


async def test_same_model_downloads_as_byte_identical_zips(client: AsyncClient) -> None:
    project_id = await build_blog(client)

    first = await client.get(f"/projects/{project_id}/generate/download")
    second = await client.get(f"/projects/{project_id}/generate/download")

    assert first.content == second.content


async def test_each_download_is_recorded_with_its_spec_snapshot(client: AsyncClient) -> None:
    project_id = await build_blog(client)
    spec_before = (await client.get(f"/projects/{project_id}/spec")).json()
    first = await client.get(f"/projects/{project_id}/generate/download")

    entities = (await client.get(f"/projects/{project_id}/entities")).json()["items"]
    tag = next(e for e in entities if e["name"] == "Tag")
    await client.post(f"/entities/{tag['id']}/fields", json={"name": "color", "type": "string"})
    spec_after = (await client.get(f"/projects/{project_id}/spec")).json()
    second = await client.get(f"/projects/{project_id}/generate/download")

    history = (await client.get(f"/projects/{project_id}/generations")).json()
    assert history["total"] == 2
    newest, oldest = history["items"]
    assert newest["id"] == second.headers["x-generation-id"]
    assert oldest["id"] == first.headers["x-generation-id"]
    assert newest["spec_hash"] != oldest["spec_hash"]
    assert oldest["file_count"] > 0 and oldest["total_size"] > 0

    detail = (await client.get(f"/generations/{oldest['id']}")).json()
    assert detail["spec_snapshot"] == spec_before
    assert (await client.get(f"/generations/{newest['id']}")).json()["spec_snapshot"] == spec_after
    assert {"path", "size", "sha256"} == set(detail["file_manifest"][0])


async def test_invalid_model_cannot_be_generated_and_records_nothing(client: AsyncClient) -> None:
    project_id = await build_blog(client)
    entities = (await client.get(f"/projects/{project_id}/entities")).json()["items"]
    user = next(e for e in entities if e["name"] == "User")
    await client.patch(f"/entities/{user['id']}", json={"table_name": "user"})

    for response in (
        await client.post(f"/projects/{project_id}/generate/preview"),
        await client.get(f"/projects/{project_id}/generate/download"),
    ):
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "spec_invalid"
        assert [d["code"] for d in body["details"]] == ["reserved_word"]
    history = (await client.get(f"/projects/{project_id}/generations")).json()
    assert history["total"] == 0


async def test_empty_project_generates(client: AsyncClient) -> None:
    created = await client.post("/projects", json={"name": "Empty"})
    project_id = created.json()["id"]

    response = await client.get(f"/projects/{project_id}/generate/download")

    assert response.status_code == 200
    assert "empty/app/main.py" in zipfile.ZipFile(io.BytesIO(response.content)).namelist()


async def test_deleting_a_project_removes_its_history(client: AsyncClient) -> None:
    project_id = await build_blog(client)
    generation_id = (await client.get(f"/projects/{project_id}/generate/download")).headers[
        "x-generation-id"
    ]

    assert (await client.delete(f"/projects/{project_id}")).status_code == 204

    assert (await client.get(f"/generations/{generation_id}")).status_code == 404


async def test_generate_endpoints_404_for_unknown_ids(client: AsyncClient) -> None:
    assert (await client.post(f"/projects/{MISSING}/generate/preview")).status_code == 404
    assert (await client.get(f"/projects/{MISSING}/generate/download")).status_code == 404
    assert (await client.get(f"/projects/{MISSING}/generations")).status_code == 404
    assert (await client.get(f"/generations/{MISSING}")).status_code == 404
