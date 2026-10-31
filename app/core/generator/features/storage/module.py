"""The `storage` feature: file uploads into an S3-compatible bucket, scanned for malware before they
are stored, with role-based access, an append-only audit trail, a `file` field type for entities,
a maintenance command and the deployment notes.

Only used when the spec has an enabled `storage` block (and auth). Nothing secret is ever
rendered: bucket credentials are environment variables of the generated project.
"""

from pathlib import Path
from typing import Any

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.spec_models import SpecStorage
from app.core.validation import uses_keycloak
from app.core.validation_payments import payments_active
from app.core.validation_storage import storage_active

_TEMPLATES = Path(__file__).parent / "templates"

_ROLE_NAMES = ("upload", "share", "read", "read_all", "delete", "delete_all", "operate")

_VERBATIM = (
    "app/storage/__init__.py.tpl",
    "app/storage/access.py.tpl",
    "app/storage/audit.py.tpl",
    "app/storage/backend.py.tpl",
    "app/storage/clamav.py.tpl",
    "app/storage/limits.py.tpl",
    "app/storage/maintenance.py.tpl",
    "app/storage/models.py.tpl",
    "app/storage/names.py.tpl",
    "app/storage/router.py.tpl",
    "app/storage/schemas.py.tpl",
    "app/storage/service.py.tpl",
    "app/storage/sniff.py.tpl",
    "tests/fake_clamd.py.tpl",
    "tests/storage_support.py.tpl",
    "tests/test_storage_backend.py.tpl",
    "tests/test_storage_security.py.tpl",
    "tests/test_storage_sniff.py.tpl",
    "tests/test_storage_upload.py.tpl",
)
_RENDERED = (
    "app/storage/config.py.j2",
    "app/storage/refs.py.j2",
    "alembic/versions/0004_storage.py.j2",
    "deploy/storage/STORAGE.md.j2",
    "deploy/storage/bucket-policy.json.j2",
    "deploy/storage/iam-policy.json.j2",
    "deploy/storage/lifecycle.json.j2",
    "docs/storage-security.md.j2",
)

# Pinned, never "latest": an audit needs to know exactly which version ships.
CLAMAV_IMAGE = "clamav/clamav:1.5.4"
# The dev S3 server of the generated compose file. MinIO's community edition no longer publishes
# images (October 2025), so a different, maintained, S3-compatible server stands in for local work.
# The application only speaks the S3 API: production points STORAGE_ENDPOINT_URL at any server.
DEV_S3_IMAGE = "chrislusf/seaweedfs:4.48"
# Headroom clamd needs above the largest accepted file (archive members, scan buffers).
CLAMD_HEADROOM_MB = 16


def active(project: ProjectCtx) -> SpecStorage | None:
    """The storage block when storage is switched on (and auth is, which it needs)."""
    if project.auth is None or not storage_active(project.spec):
        return None
    return project.spec.storage


def clamd_limit_mb(storage: SpecStorage) -> int:
    return storage.max_file_mb + CLAMD_HEADROOM_MB


class StorageModule:
    name = "storage"
    manifest = ModuleManifest(id="storage", version="1", depends_on=('auth',))

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def context(self, project: ProjectCtx, storage: SpecStorage) -> dict[str, Any]:
        references = sorted(
            (entity.table, field.name)
            for entity in project.entities
            for field in entity.file_fields
        )
        quota = storage.user_quota_mb
        return {
            "s": storage,
            "role_names": _ROLE_NAMES,
            "roles": storage.roles.model_dump(),
            "multi_tenant": bool(project.auth is not None and project.auth.multi_tenant),
            "quota_bytes": quota * 1024 * 1024 if quota is not None else None,
            "references": references,
            "down_revision": "0003" if payments_active(project.spec) else "0002",
            "audit_days": storage.security.audit_retention_days,
            "name": project.name,
            "slug": project.slug,
            "minio": storage.backend == "minio",
            "kc": uses_keycloak(project.auth),
            "clamav_image": CLAMAV_IMAGE,
            "dev_s3_image": DEV_S3_IMAGE,
            "clamd_limit_mb": clamd_limit_mb(storage),
            "file_entities": sorted({table for table, _column in references}),
        }

    def render(self, project: ProjectCtx) -> FileTree:
        storage = active(project)
        if storage is None:
            return {}
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template)
            for template in _VERBATIM
        }
        context = self.context(project, storage)
        for template in _RENDERED:
            files[template.rsplit(".", 1)[0]] = render_template(self._env, template, **context)
        return files
