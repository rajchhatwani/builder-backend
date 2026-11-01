import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    AuthCustomFieldType,
    AuthOperation,
    AuthProvider,
    DbEngine,
    DeletionMode,
    FieldType,
    JwtAlgorithm,
    KeycloakMode,
    MfaMode,
    OnDelete,
    RelationKind,
    RowRule,
    SmsProvider,
    TokenStore,
)
from app.core.spec_models import (
    Spec,
    SpecAuth,
    SpecAuthCustomField,
    SpecAuthorization,
    SpecDeployment,
    SpecDocuments,
    SpecEntity,
    SpecEntityOptions,
    SpecField,
    SpecIdentityProvider,
    SpecKeycloak,
    SpecObservability,
    SpecPasswordReset,
    SpecPayments,
    SpecPermission,
    SpecProject,
    SpecRegistration,
    SpecRelation,
    SpecRole,
    SpecSmsConfig,
    SpecSmtpConfig,
    SpecStateMachine,
    SpecStorage,
)
from app.core.validation import ValidationIssue, validate
from app.exceptions import AppError
from app.models.auth_config import ProjectAuthConfig
from app.models.auth_custom_field import AuthCustomField
from app.models.authorization_config import ProjectAuthorization
from app.models.behavior_config import ProjectBehavior
from app.models.deployment_config import ProjectDeployment
from app.models.documents_config import ProjectDocuments
from app.models.entity import Entity
from app.models.field import Field
from app.models.keycloak_config import ProjectKeycloakConfig
from app.models.observability_config import ProjectObservability
from app.models.payments_config import ProjectPaymentsConfig
from app.models.project import Project
from app.models.project_permission import ProjectPermission
from app.models.project_role import ProjectRole
from app.models.relation import Relation
from app.models.storage_config import ProjectStorageConfig
from app.services.authorization_service import apply_spec as apply_authorization_spec
from app.services.authorization_service import config_to_spec as authorization_config_to_spec
from app.services.behavior_service import (
    BLOCKS,
    HISTORY,
    HOOKS,
    LISTS,
    SEED,
    SEQUENCES,
    SETTINGS,
    BehaviorService,
    apply_section,
)
from app.services.deployment_service import apply_spec as apply_deployment_spec
from app.services.deployment_service import config_to_spec as deployment_config_to_spec
from app.services.documents_service import apply_spec as apply_documents_spec
from app.services.documents_service import config_to_spec as documents_config_to_spec
from app.services.observability_service import apply_spec as apply_observability_spec
from app.services.observability_service import config_to_spec as observability_config_to_spec
from app.services.payments_service import apply_spec, config_to_spec
from app.services.storage_service import apply_spec as apply_storage_spec
from app.services.storage_service import config_to_spec as storage_config_to_spec


class SpecService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _get_project_or_404(self, project_id: uuid.UUID) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise AppError(code="not_found", message="project not found", status_code=404)
        return project

    async def assemble(self, project_id: uuid.UUID) -> Spec:
        """Build the spec from the normalized tables. Ordering is fully deterministic:
        entities by name, fields by position, relations by (from entity, from_name, to entity)."""
        project = await self._get_project_or_404(project_id)
        entities = list(
            (
                await self.session.execute(
                    select(Entity).where(Entity.project_id == project_id).order_by(Entity.name)
                )
            ).scalars()
        )
        names_by_id = {e.id: e.name for e in entities}
        fields = (
            await self.session.execute(
                select(Field)
                .where(Field.entity_id.in_(names_by_id))
                .order_by(Field.position, Field.name)
            )
        ).scalars()
        fields_by_entity: dict[uuid.UUID, list[SpecField]] = {e.id: [] for e in entities}
        for f in fields:
            fields_by_entity[f.entity_id].append(
                SpecField(
                    name=f.name,
                    type=f.type.value,
                    required=f.required,
                    unique=f.unique,
                    indexed=f.indexed,
                    default=f.default,
                    max_length=f.max_length,
                    min_value=f.min_value,
                    max_value=f.max_value,
                    enum_values=f.enum_values,
                )
            )
        relations = (
            await self.session.execute(select(Relation).where(Relation.project_id == project_id))
        ).scalars()
        spec_relations = sorted(
            (
                SpecRelation(
                    kind=r.kind.value,
                    from_entity=names_by_id[r.from_entity_id],
                    to_entity=names_by_id[r.to_entity_id],
                    from_name=r.from_name,
                    to_name=r.to_name,
                    on_delete=r.on_delete.value,
                    required=r.required,
                )
                for r in relations
            ),
            key=lambda r: (r.from_entity, r.from_name, r.to_entity),
        )
        # ── Auth block (optional) ──────────────────────────────────────────────
        auth_config_row = (
            await self.session.execute(
                select(ProjectAuthConfig).where(ProjectAuthConfig.project_id == project_id)
            )
        ).scalar_one_or_none()

        spec_auth: SpecAuth | None = None
        if auth_config_row is not None:
            # Roles
            role_rows = list(
                (
                    await self.session.execute(
                        select(ProjectRole)
                        .where(ProjectRole.project_id == project_id)
                        .order_by(ProjectRole.position, ProjectRole.name)
                    )
                ).scalars()
            )
            # Permissions
            perm_rows = list(
                (
                    await self.session.execute(
                        select(ProjectPermission)
                        .where(ProjectPermission.project_id == project_id)
                        .order_by(ProjectPermission.entity_id, ProjectPermission.operation)
                    )
                ).scalars()
            )
            # Custom fields
            cf_rows = list(
                (
                    await self.session.execute(
                        select(AuthCustomField)
                        .where(AuthCustomField.project_id == project_id)
                        .order_by(AuthCustomField.position, AuthCustomField.name)
                    )
                ).scalars()
            )

            kc_row = (
                await self.session.execute(
                    select(ProjectKeycloakConfig).where(
                        ProjectKeycloakConfig.project_id == project_id
                    )
                )
            ).scalar_one_or_none()

            ac = auth_config_row
            spec_auth = SpecAuth(
                enabled=ac.enabled,
                provider=ac.provider.value,
                keycloak=_keycloak_to_spec(kc_row) if kc_row is not None else None,
                token_store=ac.token_store.value,
                access_token_ttl_minutes=ac.access_token_ttl_minutes,
                refresh_token_ttl_days=ac.refresh_token_ttl_days,
                jwt_algorithm=ac.jwt_algorithm.value,
                deletion_mode=ac.deletion_mode.value,
                multi_tenant=ac.multi_tenant,
                security_headers_enabled=ac.security_headers_enabled,
                app_name=ac.app_name,
                app_url=ac.app_url,
                password_reset=SpecPasswordReset(
                    email_magic_link=ac.email_magic_link_enabled,
                    sms_otp=ac.sms_otp_enabled,
                    otp_ttl_minutes=ac.otp_ttl_minutes,
                ),
                registration=SpecRegistration(
                    email_verification_required=ac.email_verification_required,
                    invite_only=ac.invite_only,
                    custom_fields=[
                        SpecAuthCustomField(
                            name=cf.name,
                            label=cf.label,
                            type=cf.type.value,
                            required=cf.required,
                            unique=cf.unique,
                            indexed=cf.indexed,
                            min_length=cf.min_length,
                            max_length=cf.max_length,
                            min_value=cf.min_value,
                            max_value=cf.max_value,
                            default_value=cf.default_value,
                            enum_values=cf.enum_values,
                        )
                        for cf in cf_rows
                    ],
                ),
                smtp=(SpecSmtpConfig.model_validate(ac.smtp_config) if ac.smtp_config else None),
                sms_provider=ac.sms_provider.value if ac.sms_provider else None,
                sms=(SpecSmsConfig.model_validate(ac.sms_config) if ac.sms_config else None),
                login_rate_limit=ac.login_rate_limit,
                register_rate_limit=ac.register_rate_limit,
                reset_rate_limit=ac.reset_rate_limit,
                roles=[
                    SpecRole(
                        name=r.name,
                        label=r.label,
                        is_default=r.is_default,
                        self_assignable=r.self_assignable,
                        invite_only=r.invite_only,
                        inherits_from=r.inherits_from,
                    )
                    for r in role_rows
                ],
                permissions=[
                    SpecPermission(
                        entity=names_by_id[p.entity_id],
                        operation=AuthOperation(p.operation).value,
                        roles=p.roles,
                        row_rule=RowRule(p.row_rule).value if p.row_rule else None,
                        custom_filter_field=p.custom_filter_field,
                        custom_filter_value=p.custom_filter_value,
                    )
                    for p in perm_rows
                    if p.entity_id in names_by_id  # guard orphaned refs
                ],
            )

        return Spec(
            project=SpecProject(
                name=project.name,
                slug=project.slug,
                description=project.description,
                db_engine=project.db_engine.value,
            ),
            entities=[
                SpecEntity(
                    name=e.name,
                    table_name=e.table_name,
                    plural_path=e.plural_path,
                    options=SpecEntityOptions.model_validate(e.options),
                    fields=fields_by_entity[e.id],
                )
                for e in entities
            ],
            relations=spec_relations,
            auth=spec_auth,
            payments=await self._payments_spec(project_id),
            storage=await self._storage_spec(project_id),
            authorization=await self._authorization_spec(project_id),
            observability=await self._observability_spec(project_id),
            state_machines=await BehaviorService(self.session).machines(project_id),
            settings=await BehaviorService(self.session).settings(project_id),
            sequences=await BehaviorService(self.session).sequences(project_id),
            lists=await BehaviorService(self.session).lists(project_id),
            history=await BehaviorService(self.session).history(project_id),
            hooks=await BehaviorService(self.session).hooks(project_id),
            seed=await BehaviorService(self.session).seed(project_id),
            **{key: await BehaviorService(self.session).block(project_id, key) for key in BLOCKS},
            deployment=await self._deployment_spec(project_id),
            documents=await self._documents_spec(project_id),
        )

    async def _payments_spec(self, project_id: uuid.UUID) -> SpecPayments | None:
        row = (
            await self.session.execute(
                select(ProjectPaymentsConfig).where(ProjectPaymentsConfig.project_id == project_id)
            )
        ).scalar_one_or_none()
        return config_to_spec(row) if row is not None else None

    async def _storage_spec(self, project_id: uuid.UUID) -> SpecStorage | None:
        row = (
            await self.session.execute(
                select(ProjectStorageConfig).where(ProjectStorageConfig.project_id == project_id)
            )
        ).scalar_one_or_none()
        return storage_config_to_spec(row) if row is not None else None

    async def _authorization_spec(self, project_id: uuid.UUID) -> SpecAuthorization | None:
        row = (
            await self.session.execute(
                select(ProjectAuthorization).where(ProjectAuthorization.project_id == project_id)
            )
        ).scalar_one_or_none()
        return authorization_config_to_spec(row) if row is not None else None

    async def _observability_spec(self, project_id: uuid.UUID) -> SpecObservability | None:
        row = (
            await self.session.execute(
                select(ProjectObservability).where(ProjectObservability.project_id == project_id)
            )
        ).scalar_one_or_none()
        return observability_config_to_spec(row) if row is not None else None

    async def _deployment_spec(self, project_id: uuid.UUID) -> SpecDeployment | None:
        row = (
            await self.session.execute(
                select(ProjectDeployment).where(ProjectDeployment.project_id == project_id)
            )
        ).scalar_one_or_none()
        return deployment_config_to_spec(row) if row is not None else None

    async def _documents_spec(self, project_id: uuid.UUID) -> SpecDocuments | None:
        row = (
            await self.session.execute(
                select(ProjectDocuments).where(ProjectDocuments.project_id == project_id)
            )
        ).scalar_one_or_none()
        return documents_config_to_spec(row) if row is not None else None

    async def validate(self, project_id: uuid.UUID) -> list[ValidationIssue]:
        return validate(await self.assemble(project_id))

    async def replace(
        self, project_id: uuid.UUID, spec: Spec, *, validate_spec: bool = True
    ) -> Spec:
        """Replace the project's entities, fields and relations with the spec's.

        The project's own identity (name, slug, description) is left alone: a spec
        exported from one project can be imported into another without a slug clash.
        The `auth` block is replaced as a whole when the spec has one. A spec without it
        leaves the project's auth settings as they are (permissions are re-attached to the
        re-created entities by name). Credentials are never part of a spec.
        All-or-nothing: an invalid spec changes nothing. The op-log passes `validate_spec=False`
        only to return to a state the project already had (undo, redo, restore).
        """
        project = await self._get_project_or_404(project_id)
        issues = validate(spec) if validate_spec else []
        if issues:
            raise AppError(
                code="spec_invalid",
                message=f"spec has {len(issues)} validation issue(s)",
                status_code=422,
                details=[issue.model_dump() for issue in issues],
            )

        # Deleting entities cascades to their permissions, so remember them first.
        kept_permissions = (
            await self._permissions_by_entity_name(project_id) if spec.auth is None else []
        )
        await self.session.execute(
            delete(Relation).where(Relation.project_id == project_id),
            execution_options={"synchronize_session": False},
        )
        await self.session.execute(
            delete(Entity).where(Entity.project_id == project_id),
            execution_options={"synchronize_session": False},
        )

        ids_by_name: dict[str, uuid.UUID] = {}
        for spec_entity in spec.entities:
            entity = Entity(
                id=uuid.uuid4(),
                project_id=project_id,
                name=spec_entity.name,
                table_name=spec_entity.table_name,
                plural_path=spec_entity.plural_path,
                options=spec_entity.options.model_dump(),
            )
            ids_by_name[entity.name] = entity.id
            self.session.add(entity)
            for position, f in enumerate(spec_entity.fields):
                self.session.add(
                    Field(
                        entity_id=entity.id,
                        name=f.name,
                        type=FieldType(f.type),
                        required=f.required,
                        unique=f.unique,
                        indexed=f.indexed,
                        default=f.default,
                        max_length=f.max_length,
                        min_value=f.min_value,
                        max_value=f.max_value,
                        enum_values=f.enum_values,
                        position=position,
                    )
                )
        # Entities must exist before fields/relations reference them.
        await self.session.flush()
        for r in spec.relations:
            self.session.add(
                Relation(
                    project_id=project_id,
                    kind=RelationKind(r.kind),
                    from_entity_id=ids_by_name[r.from_entity],
                    to_entity_id=ids_by_name[r.to_entity],
                    from_name=r.from_name,
                    to_name=r.to_name,
                    on_delete=OnDelete(r.on_delete),
                    required=r.required,
                )
            )
        if spec.auth is not None:
            await self._replace_auth(project_id, spec.auth, ids_by_name)
        else:
            self._add_permissions(
                project_id, [p for p in kept_permissions if p.entity in ids_by_name], ids_by_name
            )
        if spec.payments is not None:
            await self._replace_payments(project_id, spec.payments)
        if spec.storage is not None:
            await self._replace_storage(project_id, spec.storage)
        if spec.authorization is not None:
            await self._replace_authorization(project_id, spec.authorization)
        if spec.observability is not None:
            await self._replace_observability(project_id, spec.observability)
        if spec.state_machines:
            await self._replace_state_machines(project_id, spec.state_machines)
        for key, items in (
            (SETTINGS, spec.settings),
            (SEQUENCES, spec.sequences),
            (LISTS, spec.lists),
            (HISTORY, spec.history),
            (HOOKS, spec.hooks),
            (SEED, spec.seed),
        ):
            if items:
                await self._replace_behavior_section(project_id, key, items)
        for block in BLOCKS:
            if getattr(spec, block) is not None:
                await self._replace_behavior_section(project_id, block, getattr(spec, block))
        if spec.deployment is not None:
            await self._replace_deployment(project_id, spec.deployment)
        if spec.documents is not None:
            await self._replace_documents(project_id, spec.documents)
        project.db_engine = DbEngine(spec.project.db_engine)
        project.version += 1
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppError(
                code="conflict", message="spec conflicts with existing data", status_code=409
            ) from exc
        return await self.assemble(project_id)

    # --- auth import ------------------------------------------------------------------

    async def _permissions_by_entity_name(self, project_id: uuid.UUID) -> list[SpecPermission]:
        rows = (
            await self.session.execute(
                select(ProjectPermission, Entity.name)
                .join(Entity, Entity.id == ProjectPermission.entity_id)
                .where(ProjectPermission.project_id == project_id)
            )
        ).all()
        return [
            SpecPermission(
                entity=entity_name,
                operation=AuthOperation(p.operation).value,
                roles=list(p.roles),
                row_rule=RowRule(p.row_rule).value if p.row_rule else None,
                custom_filter_field=p.custom_filter_field,
                custom_filter_value=p.custom_filter_value,
            )
            for p, entity_name in rows
        ]

    def _add_permissions(
        self,
        project_id: uuid.UUID,
        permissions: list[SpecPermission],
        ids_by_name: dict[str, uuid.UUID],
    ) -> None:
        for p in permissions:
            self.session.add(
                ProjectPermission(
                    project_id=project_id,
                    entity_id=ids_by_name[p.entity],
                    operation=AuthOperation(p.operation),
                    roles=list(p.roles),
                    row_rule=RowRule(p.row_rule) if p.row_rule else None,
                    custom_filter_field=p.custom_filter_field,
                    custom_filter_value=p.custom_filter_value,
                )
            )

    async def _replace_auth(
        self, project_id: uuid.UUID, auth: SpecAuth, ids_by_name: dict[str, uuid.UUID]
    ) -> None:
        for model in (ProjectPermission, ProjectRole, AuthCustomField):
            await self.session.execute(
                delete(model).where(model.project_id == project_id),
                execution_options={"synchronize_session": False},
            )
        config = (
            await self.session.execute(
                select(ProjectAuthConfig).where(ProjectAuthConfig.project_id == project_id)
            )
        ).scalar_one_or_none()
        if config is None:
            config = ProjectAuthConfig(project_id=project_id)
            self.session.add(config)
        config.enabled = auth.enabled
        config.provider = AuthProvider(auth.provider)
        await self._replace_keycloak(project_id, auth.keycloak)
        config.token_store = TokenStore(auth.token_store)
        config.access_token_ttl_minutes = auth.access_token_ttl_minutes
        config.refresh_token_ttl_days = auth.refresh_token_ttl_days
        config.jwt_algorithm = JwtAlgorithm(auth.jwt_algorithm)
        config.email_magic_link_enabled = auth.password_reset.email_magic_link
        config.sms_otp_enabled = auth.password_reset.sms_otp
        config.otp_ttl_minutes = auth.password_reset.otp_ttl_minutes
        config.email_verification_required = auth.registration.email_verification_required
        config.invite_only = auth.registration.invite_only
        config.multi_tenant = auth.multi_tenant
        config.deletion_mode = DeletionMode(auth.deletion_mode)
        config.smtp_config = auth.smtp.model_dump() if auth.smtp else None
        config.sms_provider = SmsProvider(auth.sms_provider) if auth.sms_provider else None
        config.sms_config = auth.sms.model_dump() if auth.sms else None
        config.login_rate_limit = auth.login_rate_limit
        config.register_rate_limit = auth.register_rate_limit
        config.reset_rate_limit = auth.reset_rate_limit
        config.security_headers_enabled = auth.security_headers_enabled
        config.app_name = auth.app_name
        config.app_url = auth.app_url
        for position, role in enumerate(auth.roles):
            self.session.add(
                ProjectRole(
                    project_id=project_id,
                    name=role.name,
                    label=role.label,
                    is_default=role.is_default,
                    self_assignable=role.self_assignable,
                    invite_only=role.invite_only,
                    inherits_from=role.inherits_from,
                    position=position,
                )
            )
        for position, f in enumerate(auth.registration.custom_fields):
            self.session.add(
                AuthCustomField(
                    project_id=project_id,
                    name=f.name,
                    label=f.label,
                    type=AuthCustomFieldType(f.type),
                    required=f.required,
                    unique=f.unique,
                    indexed=f.indexed,
                    min_length=f.min_length,
                    max_length=f.max_length,
                    min_value=f.min_value,
                    max_value=f.max_value,
                    default_value=f.default_value,
                    enum_values=f.enum_values,
                    position=position,
                )
            )
        self._add_permissions(project_id, auth.permissions, ids_by_name)

    async def _replace_payments(self, project_id: uuid.UUID, payments: SpecPayments) -> None:
        # A spec without a payments block leaves the settings alone; one with it replaces them.
        row = (
            await self.session.execute(
                select(ProjectPaymentsConfig).where(ProjectPaymentsConfig.project_id == project_id)
            )
        ).scalar_one_or_none()
        if row is None:
            row = ProjectPaymentsConfig(project_id=project_id)
            self.session.add(row)
        apply_spec(row, payments)

    async def _replace_storage(self, project_id: uuid.UUID, storage: SpecStorage) -> None:
        # A spec without a storage block leaves the settings alone; one with it replaces them.
        row = (
            await self.session.execute(
                select(ProjectStorageConfig).where(ProjectStorageConfig.project_id == project_id)
            )
        ).scalar_one_or_none()
        if row is None:
            row = ProjectStorageConfig(project_id=project_id)
            self.session.add(row)
        apply_storage_spec(row, storage)

    async def _replace_authorization(
        self, project_id: uuid.UUID, authorization: SpecAuthorization
    ) -> None:
        # No authorization block leaves the settings alone; one with it replaces them.
        row = (
            await self.session.execute(
                select(ProjectAuthorization).where(ProjectAuthorization.project_id == project_id)
            )
        ).scalar_one_or_none()
        if row is None:
            row = ProjectAuthorization(project_id=project_id, version=1)
            self.session.add(row)
        else:
            row.version += 1
        apply_authorization_spec(row, authorization)

    async def _replace_state_machines(
        self, project_id: uuid.UUID, machines: list[SpecStateMachine]
    ) -> None:
        await self._replace_behavior_section(project_id, "state_machines", machines)

    async def _replace_behavior_section(
        self, project_id: uuid.UUID, key: str, items: list[Any]
    ) -> None:
        # An import without items for a section leaves it alone; one with them replaces it.
        row = (
            await self.session.execute(
                select(ProjectBehavior).where(ProjectBehavior.project_id == project_id)
            )
        ).scalar_one_or_none()
        if row is None:
            row = ProjectBehavior(project_id=project_id, version=1, sections={})
            self.session.add(row)
        else:
            row.version += 1
        apply_section(row, key, items)

    async def _replace_observability(
        self, project_id: uuid.UUID, observability: SpecObservability
    ) -> None:
        # No observability block leaves the settings alone; one with it replaces them.
        row = (
            await self.session.execute(
                select(ProjectObservability).where(ProjectObservability.project_id == project_id)
            )
        ).scalar_one_or_none()
        if row is None:
            row = ProjectObservability(project_id=project_id, version=1)
            self.session.add(row)
        else:
            row.version += 1
        apply_observability_spec(row, observability)

    async def _replace_deployment(self, project_id: uuid.UUID, deployment: SpecDeployment) -> None:
        # No deployment block leaves the settings alone; one with it replaces them.
        row = (
            await self.session.execute(
                select(ProjectDeployment).where(ProjectDeployment.project_id == project_id)
            )
        ).scalar_one_or_none()
        if row is None:
            row = ProjectDeployment(project_id=project_id, version=1)
            self.session.add(row)
        else:
            row.version += 1
        apply_deployment_spec(row, deployment)

    async def _replace_documents(self, project_id: uuid.UUID, documents: SpecDocuments) -> None:
        # No documents block leaves the settings alone; one with it replaces them.
        row = (
            await self.session.execute(
                select(ProjectDocuments).where(ProjectDocuments.project_id == project_id)
            )
        ).scalar_one_or_none()
        if row is None:
            row = ProjectDocuments(project_id=project_id, version=1)
            self.session.add(row)
        else:
            row.version += 1
        apply_documents_spec(row, documents)

    async def _replace_keycloak(self, project_id: uuid.UUID, kc: SpecKeycloak | None) -> None:
        row = (
            await self.session.execute(
                select(ProjectKeycloakConfig).where(ProjectKeycloakConfig.project_id == project_id)
            )
        ).scalar_one_or_none()
        if kc is None:
            if row is not None:
                await self.session.delete(row)
            return
        if row is None:
            row = ProjectKeycloakConfig(project_id=project_id)
            self.session.add(row)
        # source_project_id is builder bookkeeping, not part of the spec: an import keeps it.
        row.mode = KeycloakMode(kc.mode)
        row.realm = kc.realm
        row.api_client_id = kc.api_client_id
        row.web_client_id = kc.web_client_id
        row.redirect_uris = list(kc.redirect_uris)
        row.password_min_length = kc.password_min_length
        row.mfa = MfaMode(kc.mfa)
        row.session_idle_minutes = kc.session_idle_minutes
        row.session_max_hours = kc.session_max_hours
        row.audit_retention_days = kc.audit_retention_days
        row.identity_providers = [p.model_dump() for p in kc.identity_providers]


def _keycloak_to_spec(row: ProjectKeycloakConfig) -> SpecKeycloak:
    return SpecKeycloak(
        mode=row.mode.value,
        realm=row.realm,
        api_client_id=row.api_client_id,
        web_client_id=row.web_client_id,
        redirect_uris=list(row.redirect_uris),
        password_min_length=row.password_min_length,
        mfa=row.mfa.value,
        session_idle_minutes=row.session_idle_minutes,
        session_max_hours=row.session_max_hours,
        audit_retention_days=row.audit_retention_days,
        identity_providers=[SpecIdentityProvider.model_validate(p) for p in row.identity_providers],
    )
