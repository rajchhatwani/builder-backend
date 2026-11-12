"""Real OpenSearch e2e: the generated search project against opensearchproject/opensearch:2 (single node, security
plugin off) and a real Postgres; runs tests/e2e/search_opensearch_scenarios.py. Skips ONLY when the image is absent
locally (then: `docker pull opensearchproject/opensearch:2` and rerun this file). Needs Docker."""
import shutil
import subprocess
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer

from tests.e2e.test_generated_project import ok, postgres, project_dir, run  # noqa: F401

HERE = Path(__file__).resolve().parent
IMAGE = "opensearchproject/opensearch:2"


def _image_present() -> bool:
    return subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode == 0


@pytest.fixture(scope="module")
def opensearch() -> Iterator[str]:
    if not _image_present():
        pytest.skip(f"image {IMAGE} is not present: docker pull {IMAGE}, then rerun")
    container = (
        DockerContainer(IMAGE)
        .with_env("discovery.type", "single-node")
        .with_env("DISABLE_SECURITY_PLUGIN", "true")
        .with_env("DISABLE_INSTALL_DEMO_CONFIG", "true")
        .with_env("OPENSEARCH_JAVA_OPTS", "-Xms512m -Xmx512m")
        .with_exposed_ports(9200)
    )
    with container:
        url = f"http://{container.get_container_host_ip()}:{container.get_exposed_port(9200)}"
        deadline = time.time() + 180
        while True:
            try:
                with urllib.request.urlopen(url + "/_cluster/health?wait_for_status=yellow&timeout=5s", timeout=10) as r:  # noqa: S310
                    if r.status == 200:
                        break
            except OSError:
                pass
            assert time.time() < deadline, "opensearch did not become healthy in 180 s"
            time.sleep(2)
        yield url


def test_the_generated_search_against_real_opensearch(
    postgres: PostgresContainer,  # noqa: F811
    opensearch: str,
    tmp_path_factory,  # noqa: ANN001
) -> None:
    root = project_dir(tmp_path_factory, "search")
    shutil.copy(HERE / "search_opensearch_scenarios.py", root / "tests" / "test_scenarios.py")
    url = (
        f"postgresql+asyncpg://{postgres.username}:{postgres.password}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/search_os_test"
    )
    ok(run(["-m", "tests._prepare_db"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    output = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider"], root, url, SEARCH_OS_URL=opensearch))
    assert " passed" in output and "failed" not in output, output
