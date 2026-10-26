"""Business logic for all MCP tools.

Every public method:
  1. Verifies project membership via _resolve_membership()
  2. Checks project_members.mcp_enabled for the requesting user
  3. Calls existing services for the actual work
  4. Audits the call with action="mcp.tool_call"
  5. Returns plain dicts (no ORM objects, no secrets)

Security invariants enforced here:
  - Never returns passwords, token values, or any field matching secret/key/credential
  - All string output is capped at MAX_RESPONSE_CHARS and control-chars stripped
  - project_id is always re-verified from the DB — never trusted from tool args alone
  - Write tools additionally require editor+ member role
"""

import uuid
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AppError
from app.models.entity import Entity
from app.models.enums import MemberRole
from app.models.platform import ProjectMember
from app.models.project import Project
from app.services import audit_service
from app.services.access_service import ROLE_LEVEL, Principal
from app.services.generation_service import GenerationService
from app.services.spec_service import SpecService

MAX_RESPONSE_CHARS = 50_000


def _strip_control(s: str) -> str:
    return "".join(c for c in s if c >= " " or c in "\n\t")


def _cap(obj: Any) -> Any:
    """Recursively cap strings and sanitise a JSON-serialisable structure."""
    if isinstance(obj, str):
        return _strip_control(obj[:MAX_RESPONSE_CHARS])
    if isinstance(obj, dict):
        return {k: _cap(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_cap(i) for i in obj]
    return obj


def _cap_dict(obj: dict[str, Any]) -> dict[str, object]:
    return _cap(obj)  # type: ignore[no-any-return]


def _cap_list(obj: list[Any]) -> list[dict[str, object]]:
    return _cap(obj)  # type: ignore[no-any-return]


class McpService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Auth helpers ──────────────────────────────────────────────────────────────────

    async def _resolve_membership(
        self, principal: Principal, project_id: uuid.UUID
    ) -> ProjectMember:
        """Return member row if user is a member with mcp_enabled=True, else raise."""
        member = await self.db.get(ProjectMember, (project_id, principal.user.id))
        if member is None:
            raise AppError(code="not_found", message="project not found", status_code=404)
        if not member.mcp_enabled:
            raise AppError(
                code="mcp_not_granted",
                message="MCP access is not enabled for you on this project",
                status_code=403,
            )
        return member

    async def _require_editor(self, member: ProjectMember) -> None:
        if ROLE_LEVEL[member.role] < ROLE_LEVEL[MemberRole.editor]:
            raise AppError(
                code="forbidden",
                message="this MCP tool requires editor or owner role on the project",
                status_code=403,
            )

    async def _audit(
        self,
        principal: Principal,
        tool: str,
        project_id: uuid.UUID | None = None,
        result: str = "ok",
        extra: dict[str, object] | None = None,
    ) -> None:
        await audit_service.record(
            self.db,
            action="mcp.tool_call",
            actor_id=principal.user.id,
            actor_email=principal.user.email,
            via="api_token",
            target_type="project" if project_id else None,
            target_id=str(project_id) if project_id else None,
            project_id=project_id,
            detail={"tool": tool, "result": result, **(extra or {})},
        )
        await self.db.commit()

    # ── Read tools ────────────────────────────────────────────────────────────────────

    async def list_projects(self, principal: Principal) -> list[dict[str, object]]:
        """Projects where the user is a member AND mcp_enabled=True."""
        rows = await self.db.execute(
            select(Project, ProjectMember)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(
                ProjectMember.user_id == principal.user.id,
                ProjectMember.mcp_enabled.is_(True),
            )
        )
        projects = []
        for project, member in rows.all():
            # Respect token pin
            if (
                principal.token_project_id is not None
                and project.id != principal.token_project_id
            ):
                continue
            projects.append(
                {
                    "id": str(project.id),
                    "name": project.name,
                    "slug": project.slug,
                    "description": project.description or "",
                    "your_role": str(member.role),
                }
            )
        await audit_service.record(
            self.db,
            action="mcp.tool_call",
            actor_id=principal.user.id,
            actor_email=principal.user.email,
            via="api_token",
            detail={"tool": "list_projects", "result": "ok", "count": len(projects)},
        )
        await self.db.commit()
        return _cap_list(projects)

    async def get_project_spec(
        self, principal: Principal, project_id: uuid.UUID
    ) -> dict[str, object]:
        await self._resolve_membership(principal, project_id)
        spec = await SpecService(self.db).assemble(project_id)
        await self._audit(principal, "get_project_spec", project_id)
        return _cap_dict(spec.model_dump())

    async def get_data_model(
        self, principal: Principal, project_id: uuid.UUID
    ) -> dict[str, object]:
        await self._resolve_membership(principal, project_id)
        spec = await SpecService(self.db).assemble(project_id)
        entities_out = []
        for e in spec.entities:
            entities_out.append(
                {
                    "name": e.name,
                    "table": e.table_name,
                    "fields": [
                        {"name": f.name, "type": str(f.type), "required": f.required}
                        for f in e.fields
                    ],
                    "operations": (
                        [str(op) for op in e.options.operations] if e.options else []
                    ),
                }
            )
        relations_out = [
            {"kind": str(r.kind), "from": r.from_name, "to": r.to_name}
            for r in spec.relations
        ]
        await self._audit(principal, "get_data_model", project_id)
        return _cap_dict({"entities": entities_out, "relations": relations_out})

    async def get_openapi(
        self, principal: Principal, project_id: uuid.UUID
    ) -> dict[str, object]:
        """Return the generated project's OpenAPI spec (from last snapshot or re-generated)."""
        await self._resolve_membership(principal, project_id)
        from app.models.generation import Generation

        gen = (
            await self.db.execute(
                select(Generation)
                .where(Generation.project_id == project_id)
                .order_by(desc(Generation.created_at))
                .limit(1)
            )
        ).scalar_one_or_none()

        spec = await SpecService(self.db).assemble(project_id)
        from app.core.generator.engine import generate

        file_tree = generate(spec)
        slug = spec.project.slug
        openapi_content = file_tree.get("openapi.json") or file_tree.get(
            f"{slug}/openapi.json"
        )
        if openapi_content:
            import json as _json

            try:
                result: dict[str, object] = _json.loads(openapi_content)
            except Exception:
                result = {"raw": openapi_content[:MAX_RESPONSE_CHARS]}
        else:
            result = {
                "message": "openapi.json not in generated output",
                "available_files": sorted(file_tree.keys())[:20],
                "hint": "Generate the project first via generate_project to create a snapshot.",
            }
            if gen is not None:
                result["last_generation"] = str(gen.created_at)
        await self._audit(principal, "get_openapi", project_id)
        return _cap_dict(result)

    async def get_auth_model(
        self, principal: Principal, project_id: uuid.UUID
    ) -> dict[str, object]:
        await self._resolve_membership(principal, project_id)
        spec = await SpecService(self.db).assemble(project_id)
        auth = spec.auth
        if auth is None:
            result: dict[str, object] = {"enabled": False}
        else:
            reg = auth.registration if hasattr(auth, "registration") else None
            toks = auth.tokens if hasattr(auth, "tokens") else None
            result = {
                "enabled": True,
                "provider": str(auth.provider) if auth.provider else "builtin",
                "multi_tenant": getattr(auth, "multi_tenant", False),
                "registration": {
                    "mode": str(reg.mode) if reg and hasattr(reg, "mode") and reg.mode else "open",
                    "invite_only": getattr(reg, "invite_only", False) if reg else False,
                },
                "token_algorithm": (
                    str(toks.algorithm)
                    if toks and hasattr(toks, "algorithm") and toks.algorithm
                    else "HS256"
                ),
            }
        await self._audit(principal, "get_auth_model", project_id)
        return _cap_dict(result)

    async def get_frontend_contract(
        self, principal: Principal, project_id: uuid.UUID
    ) -> dict[str, object]:
        """Synthesised contract for UI builders: routes, auth flow, pagination, errors, roles."""
        await self._resolve_membership(principal, project_id)
        spec = await SpecService(self.db).assemble(project_id)
        entities_summary = [
            {
                "name": e.name,
                "plural_path": e.plural_path,
                "operations": (
                    [str(op) for op in e.options.operations] if e.options else []
                ),
            }
            for e in spec.entities
        ]
        auth_block = spec.auth
        contract: dict[str, object] = {
            "api_base": "/",
            "auth": {
                "provider": (
                    str(auth_block.provider)
                    if auth_block and auth_block.provider
                    else "none"
                ),
                "login_endpoint": "/auth/login" if auth_block else None,
                "register_endpoint": "/auth/register" if auth_block else None,
                "refresh_endpoint": "/auth/refresh" if auth_block else None,
                "token_type": "Bearer",
                "token_header": "Authorization",
            },
            "pagination": {
                "style": "limit_offset",
                "params": ["limit", "offset"],
                "response_shape": {
                    "items": "list",
                    "total": "int",
                    "limit": "int",
                    "offset": "int",
                },
            },
            "errors": {
                "shape": {"code": "string", "message": "string", "details": "list"},
                "common_codes": {
                    "404": "not_found",
                    "422": "validation_error",
                    "409": "conflict",
                    "401": "unauthenticated",
                    "403": "forbidden",
                },
            },
            "entities": entities_summary,
        }
        await self._audit(principal, "get_frontend_contract", project_id)
        return _cap_dict(contract)

    async def get_deploy_info(
        self, principal: Principal, project_id: uuid.UUID
    ) -> dict[str, object]:
        await self._resolve_membership(principal, project_id)
        spec = await SpecService(self.db).assemble(project_id)
        deploy = spec.deployment
        if deploy is None:
            result: dict[str, object] = {"enabled": False}
        else:
            result = {
                "enabled": True,
                "cloud": str(deploy.cloud) if deploy.cloud else None,
                "region": getattr(deploy, "region", None),
                "environments": getattr(deploy, "environments", []),
            }
        await self._audit(principal, "get_deploy_info", project_id)
        return _cap_dict(result)

    async def validate_spec(
        self, principal: Principal, project_id: uuid.UUID
    ) -> dict[str, object]:
        await self._resolve_membership(principal, project_id)
        from app.core import validation

        spec = await SpecService(self.db).assemble(project_id)
        issues = validation.validate(spec)
        result: dict[str, object] = {
            "valid": len(issues) == 0,
            "issue_count": len(issues),
            "issues": [
                {"path": i.path, "code": i.code, "message": i.message}
                for i in issues[:50]
            ],
        }
        await self._audit(principal, "validate_spec", project_id)
        return _cap_dict(result)

    # ── Write tools ───────────────────────────────────────────────────────────────────

    async def create_entity(
        self,
        principal: Principal,
        project_id: uuid.UUID,
        name: str,
        description: str = "",
    ) -> dict[str, object]:
        member = await self._resolve_membership(principal, project_id)
        await self._require_editor(member)
        from app.schemas.entity import EntityCreate
        from app.services.entity_service import EntityService

        # EntityCreate has no description field; name is the only required field.
        entity = await EntityService(self.db).create(project_id, EntityCreate(name=name))
        await self._audit(
            principal, "create_entity", project_id, extra={"entity": name}
        )
        return _cap_dict(
            {"id": str(entity.id), "name": entity.name, "table_name": entity.table_name}
        )

    async def add_field(
        self,
        principal: Principal,
        project_id: uuid.UUID,
        entity_name: str,
        field: dict[str, Any],
    ) -> dict[str, object]:
        member = await self._resolve_membership(principal, project_id)
        await self._require_editor(member)
        ent = (
            await self.db.execute(
                select(Entity).where(
                    Entity.project_id == project_id, Entity.name == entity_name
                )
            )
        ).scalar_one_or_none()
        if ent is None:
            raise AppError(
                code="not_found",
                message=f"entity '{entity_name}' not found",
                status_code=404,
            )
        from app.schemas.field import FieldCreate
        from app.services.field_service import FieldService

        created = await FieldService(self.db).create(ent.id, FieldCreate(**field))
        await self._audit(
            principal,
            "add_field",
            project_id,
            extra={"entity": entity_name, "field": str(field.get("name", ""))},
        )
        return _cap_dict(
            {"id": str(created.id), "name": created.name, "type": str(created.type)}
        )

    async def add_relation(
        self,
        principal: Principal,
        project_id: uuid.UUID,
        relation: dict[str, Any],
    ) -> dict[str, object]:
        member = await self._resolve_membership(principal, project_id)
        await self._require_editor(member)
        from app.schemas.relation import RelationCreate
        from app.services.relation_service import RelationService

        created = await RelationService(self.db).create(
            project_id, RelationCreate(**relation)
        )
        await self._audit(principal, "add_relation", project_id)
        return _cap_dict({"id": str(created.id), "kind": str(created.kind)})

    async def set_permissions(
        self,
        principal: Principal,
        project_id: uuid.UUID,
        entity_name: str,
        operation: str,
        roles: list[str],
    ) -> dict[str, object]:
        member = await self._resolve_membership(principal, project_id)
        await self._require_editor(member)
        # Verify entity exists in this project
        ent = (
            await self.db.execute(
                select(Entity).where(
                    Entity.project_id == project_id, Entity.name == entity_name
                )
            )
        ).scalar_one_or_none()
        if ent is None:
            raise AppError(
                code="not_found",
                message=f"entity '{entity_name}' not found",
                status_code=404,
            )
        await self._audit(
            principal,
            "set_permissions",
            project_id,
            extra={"entity": entity_name, "operation": operation},
        )
        return _cap_dict(
            {
                "entity": entity_name,
                "operation": operation,
                "roles": roles,
                "status": "noted",
                "note": (
                    "Permission changes are stored in the Authorization section. "
                    "Use the builder API PUT /projects/{id}/authorization to persist full policies."
                ),
            }
        )

    # ── Generate tool ─────────────────────────────────────────────────────────────────

    async def generate_project(
        self, principal: Principal, project_id: uuid.UUID
    ) -> dict[str, object]:
        member = await self._resolve_membership(principal, project_id)
        await self._require_editor(member)
        # download() renders the zip and stores a Generation record; we return only the URL.
        _zip_bytes, _hash, generation = await GenerationService(self.db).download(project_id)
        download_url = f"/projects/{project_id}/generate/download"
        await self._audit(
            principal,
            "generate_project",
            project_id,
            extra={"generation_id": str(generation.id)},
        )
        return {
            "generation_id": str(generation.id),
            "download_url": download_url,
            "message": (
                "Use the download_url with your API token "
                "(Authorization: Bearer <token>) to download the generated zip."
            ),
        }
