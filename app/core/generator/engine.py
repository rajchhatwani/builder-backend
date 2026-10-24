"""generate(spec) -> {path: content}. Pure: no disk, no HTTP, no clock, no randomness."""

from app.core.generator.base import FeatureModule, FileTree
from app.core.generator.context import build_context
from app.core.generator.features.auth.module import AuthModule
from app.core.generator.features.authz.module import AuthzModule
from app.core.generator.features.crud.module import CrudModule
from app.core.generator.features.deploy.module import DeployModule
from app.core.generator.features.docker.module import DockerModule
from app.core.generator.features.documents.module import DocumentsModule
from app.core.generator.features.keycloak.module import KeycloakModule
from app.core.generator.features.observability.module import ObservabilityModule
from app.core.generator.features.payments.module import PaymentsModule
from app.core.generator.features.storage.module import StorageModule
from app.core.generator.features.tests.module import TestsModule
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
    ]


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
    return dict(sorted(files.items()))
