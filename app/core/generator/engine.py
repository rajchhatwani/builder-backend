"""generate(spec) -> {path: content}. Pure: no disk, no HTTP, no clock, no randomness."""

import re

from app.core.generator.base import FeatureModule, FileTree, ModuleManifest
from app.core.generator.context import build_context
from app.core.generator.features.api_edge.module import ApiEdgeModule
from app.core.generator.features.auth.module import AuthModule
from app.core.generator.features.authz.module import AuthzModule
from app.core.generator.features.change_history.module import ChangeHistoryModule
from app.core.generator.features.crud.module import CrudModule
from app.core.generator.features.deploy.module import DeployModule
from app.core.generator.features.docker.module import DockerModule
from app.core.generator.features.documents.module import DocumentsModule
from app.core.generator.features.events.module import EventsModule
from app.core.generator.features.hooks.module import MANIFEST_PATH as HOOKS_MANIFEST_PATH
from app.core.generator.features.hooks.module import HooksModule, build_manifest
from app.core.generator.features.jobs.module import JobsModule
from app.core.generator.features.keycloak.module import KeycloakModule
from app.core.generator.features.observability.module import ObservabilityModule
from app.core.generator.features.payments.module import PaymentsModule
from app.core.generator.features.notifications.module import NotificationsModule
from app.core.generator.features.providers.module import ProvidersModule
from app.core.generator.features.webhooks.module import WebhooksModule
from app.core.generator.features.workflows.module import WorkflowsModule
from app.core.generator.features.runtime_config.module import RuntimeConfigModule
from app.core.generator.features.seed.module import SeedModule
from app.core.generator.features.state_machines.module import StateMachinesModule
from app.core.generator.features.storage.module import StorageModule
from app.core.generator.features.tests.module import TestsModule
from app.core.generator.zones import ZONES_PATH, render_zones
from app.core.spec_models import Spec
from app.core.validation import ValidationIssue, validate


class InvalidSpecError(Exception):
    def __init__(self, issues: list[ValidationIssue]) -> None:
        super().__init__(f"spec has {len(issues)} validation issue(s)")
        self.issues = issues


def default_modules() -> list[FeatureModule]:
    return [
        CrudModule(),
        DockerModule(),
        TestsModule(),
        AuthModule(),
        AuthzModule(),
        KeycloakModule(),
        PaymentsModule(),
        StorageModule(),
        ObservabilityModule(),
        DeployModule(),
        DocumentsModule(),
        StateMachinesModule(),
        RuntimeConfigModule(),
        ChangeHistoryModule(),
        HooksModule(),
        SeedModule(),
        EventsModule(),
        ApiEdgeModule(),
        JobsModule(),
        ProvidersModule(),
        WebhooksModule(),
        NotificationsModule(),
        WorkflowsModule(),
    ]


def module_registry(modules: list[FeatureModule] | None = None) -> dict[str, ModuleManifest]:
    """Every block's manifest by id, in render order. Fails on a duplicate id, an id that differs
    from the module name, or a dependency that is not registered."""
    registry: dict[str, ModuleManifest] = {}
    for module in modules if modules is not None else default_modules():
        manifest = module.manifest
        if manifest.id != module.name or manifest.id in registry:
            raise RuntimeError(f"bad or duplicate manifest id {manifest.id!r} for module {module.name!r}")
        registry[manifest.id] = manifest
    for manifest in registry.values():
        for dep in manifest.depends_on:
            if dep not in registry:
                raise RuntimeError(f"block {manifest.id!r} depends on unknown block {dep!r}")
    return registry


_MIGRATION_PATH = re.compile(r"^alembic/versions/[^/]+\.py$")
_REVISION = re.compile(r'^revision: str = "([^"]+)"$', re.M)
_DOWN_REVISION = re.compile(r"^down_revision: str \| None = .*$", re.M)
_REVISES = re.compile(r"^Revises:.*$", re.M)


def chain_migrations(files: FileTree) -> None:
    """Link every generated Alembic revision into one linear chain.

    Each feature ships its migration under a fixed revision id; here the ENABLED ones are ordered by
    id and each one's down_revision is set to the previous one (the first has none). This is the only
    place parents are decided, so any combination of features yields exactly one head."""
    found: dict[str, str] = {}
    for path, text in files.items():
        if not _MIGRATION_PATH.match(path):
            continue
        match = _REVISION.search(text)
        if match is None:
            raise RuntimeError(f"migration {path} declares no `revision: str = \"...\"` line")
        rev = match.group(1)
        if rev in found:
            raise RuntimeError(f"two migrations share revision id {rev!r}: {found[rev]} and {path}")
        found[rev] = path
    previous: str | None = None
    for rev in sorted(found):
        path = found[rev]
        value = "None" if previous is None else f'"{previous}"'
        down_line = f"down_revision: str | None = {value}"
        revises_line = f"Revises: {previous or ''}".rstrip()
        text = _DOWN_REVISION.sub(down_line.replace(chr(92), chr(92) * 2), files[path], count=1)
        files[path] = _REVISES.sub(revises_line.replace(chr(92), chr(92) * 2), text, count=1)
        previous = rev


def generate(spec: Spec, modules: list[FeatureModule] | None = None) -> FileTree:
    """Render the project for a spec. Raises InvalidSpecError if the spec has any issue.

    Output paths are relative to the project root and returned sorted by path, so the
    same spec always yields byte-identical content in the same order.
    """
    issues = validate(spec)
    if issues:
        raise InvalidSpecError(issues)
    project = build_context(spec)
    files: FileTree = {}
    for module in modules if modules is not None else default_modules():
        for path, content in module.render(project).items():
            if path in files:
                raise RuntimeError(f"feature module {module.name!r} redefines {path}")
            files[path] = content
    chain_migrations(files)
    if spec.hooks:
        files[HOOKS_MANIFEST_PATH] = build_manifest(project, files)
    files[ZONES_PATH] = render_zones(files)
    return dict(sorted(files.items()))
