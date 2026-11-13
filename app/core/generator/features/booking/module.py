"""The `booking` pack (D12 reservation engine), emitted only when the spec declares `packs.booking`
(validation requires auth with rbac):

  app/booking/config.py     roles, own_only, hold TTL, horizon, cancellation policy, resource kinds (data)
  app/booking/models.py     booking_resources, bookings
  app/booking/rules.py      pure rules: weekly schedule -> UTC slots, states, cancellation fee, capacity peak
  app/booking/schemas.py    request / response models (StrictInt quantities)
  app/booking/service.py    resources, holds (lazy expiry + sweep), availability, create / confirm / cancel
  app/booking/router.py     /booking/* routes
  alembic/versions/0037_booking.py   tables, the btree_gist EXCLUDE constraint, the state guard trigger

Same tenant treatment as the ledger: a `tenant_id` FK to auth_tenants on multi-tenant projects.
"""

import pprint
from pathlib import Path

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_booking import booking_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/booking/__init__.py.tpl",
    "app/booking/schemas.py.tpl",
    "app/booking/rules.py.tpl",
)


def booking_enabled(project: ProjectCtx) -> bool:
    return booking_active(project.spec) and project.auth is not None


class BookingModule:
    name = "booking"
    manifest = ModuleManifest(id="booking", version="1", depends_on=("crud", "auth"), pack="booking")

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not booking_enabled(project):
            return {}
        cfg = project.spec.packs.booking  # type: ignore[union-attr]
        assert cfg is not None and project.auth is not None
        tenant = project.auth.multi_tenant
        kinds = {
            k.name: {
                "mode": k.mode,
                "timezone": k.timezone,
                "slot_minutes": k.slot_minutes,
                "schedule": {d: [{"start": w.start, "end": w.end} for w in ws] for d, ws in sorted(k.schedule.items())},
                "capacity": k.capacity,
                "min_minutes": k.min_minutes,
                "max_minutes": k.max_minutes,
            }
            for k in sorted(cfg.kinds, key=lambda k: k.name)
        }
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template) for template in _VERBATIM
        }
        files["app/booking/config.py"] = render_template(
            self._env,
            "app/booking/config.py.j2",
            read_roles=tuple(cfg.read_roles),
            book_roles=tuple(cfg.book_roles),
            manage_roles=tuple(cfg.manage_roles),
            own_only=cfg.own_only,
            hold_ttl=cfg.hold_ttl_seconds,
            horizon=cfg.max_horizon_days,
            free_hours=cfg.cancellation.free_until_hours,
            fee_minor=cfg.cancellation.fee_minor,
            fee_currency=cfg.cancellation.currency,
            kinds=pprint.pformat(kinds, width=96, sort_dicts=True),
            tenant=tenant,
        )
        for name in ("models", "service", "router"):
            files[f"app/booking/{name}.py"] = render_template(
                self._env, f"app/booking/{name}.py.j2", tenant=tenant
            )
        files["alembic/versions/0037_booking.py"] = render_template(
            self._env, "alembic/versions/0037_booking.py.j2", tenant=tenant
        )
        return files
