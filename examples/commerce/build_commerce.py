"""Build the Shopify-style commerce backend in a running Backend Builder, then save its spec and the
generated project next to this file.

    python examples/commerce/build_commerce.py                 # build, validate, save spec + backend
    python examples/commerce/build_commerce.py --reset         # delete an existing "commerce" project first
    python examples/commerce/build_commerce.py --no-save       # only build and validate

Standard library only. It talks to the builder's public API (default http://localhost:8000), exactly as
the dashboard does, so everything it creates is visible there too.
"""

import argparse
import io
import json
import shutil
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "scripts"))
sys.path.insert(0, str(HERE))

import blueprint as bp  # noqa: E402
from seed import Api, Builder  # noqa: E402

SLUG = "commerce"
# Invitations and verification emails go to a local mail catcher (see README.md).
SMTP = {
    "host": "host.docker.internal",
    "port": 1025,
    "use_tls": False,
    "from_email": "store@example.com",
    "from_name": "Commerce",
}


def audit_permissions() -> list[str]:
    """An operation with no permission is open to every signed-in caller of the store, so every
    enabled operation of every entity must be listed in the blueprint."""
    granted = {(entity, op) for entity, op, _roles, _rule in bp.permissions()}
    missing = []
    for name, spec in bp.ENTITIES.items():
        for op in spec.get("ops") or bp.ALL_OPS:
            if (name, op) not in granted:
                missing.append(f"{name}.{op}")
    return missing


def build(api: Api) -> Builder:
    b = Builder(
        api,
        "Commerce",
        SLUG,
        "A Shopify-style multi-store commerce backend: catalog, inventory, customers, carts, orders, "
        "payments, refunds, fulfilment, discounts, gift cards, shipping, taxes, reviews, content.",
    )
    for name, spec in bp.ENTITIES.items():
        b.entity(
            name,
            spec["fields"],
            operations=spec.get("ops"),
            filterable=spec.get("filterable"),
            sortable=spec.get("sortable"),
            searchable=spec.get("searchable"),
            soft_delete=spec.get("soft_delete", False),
        )
    for kind, from_, to, from_name, to_name, on_delete, required in bp.RELATIONS:
        b.relation(kind, from_, to, from_name, to_name, on_delete=on_delete, required=required)
    b.auth(
        app_name="Commerce",
        app_url="http://localhost:3000",
        smtp_config=SMTP,
        multi_tenant=True,
        token_store="redis",
        jwt_algorithm="RS256",
        access_token_ttl_minutes=30,
        refresh_token_ttl_days=14,
        email_magic_link_enabled=False,
        email_verification_required=True,
        deletion_mode="soft",
        # Generous, so seeding and load tests are not throttled (per client address, per worker).
        login_rate_limit="600/minute",
        register_rate_limit="600/minute",
        reset_rate_limit="600/minute",
    )
    for position, role in enumerate(bp.ROLES):
        b.role(
            role["name"],
            role["label"],
            position=position,
            **{k: v for k, v in role.items() if k not in ("name", "label")},
        )
    for position, custom in enumerate(bp.CUSTOM_FIELDS):
        b.api.post(f"/projects/{b.id}/auth/custom-fields", {**custom, "position": position})
    b.permissions(bp.permissions())
    return b


def save(api: Api, project_id: str, out: Path) -> None:
    spec = api.get(f"/projects/{project_id}/spec")
    (out / "spec.json").write_text(
        json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    request = __import__("urllib.request").request.Request(
        f"{api.base}/projects/{project_id}/generate/download"
    )
    with __import__("urllib.request").request.urlopen(request, timeout=120) as response:
        archive = zipfile.ZipFile(io.BytesIO(response.read()))
    target = out / "backend"
    env_file = target / ".env"
    kept_env = (
        env_file.read_bytes() if env_file.exists() else None
    )  # local settings survive a rebuild
    if target.exists():
        shutil.rmtree(target)
    for info in archive.infolist():
        relative = info.filename.split("/", 1)[1] if "/" in info.filename else ""
        if not relative or info.is_dir():
            continue
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(archive.read(info))
    if kept_env is not None:
        env_file.write_bytes(kept_env)
    print(f"  saved spec.json and backend/ ({len(archive.infolist())} files) in {out}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--reset", action="store_true", help="delete and recreate the project")
    parser.add_argument(
        "--no-save", action="store_true", help="do not write spec.json and backend/"
    )
    args = parser.parse_args()

    unprotected = audit_permissions()
    if unprotected:
        print(
            "operations without a permission (open to every signed-in user):",
            ", ".join(unprotected),
        )
        return 1
    api = Api(args.base_url)
    api.get("/health")
    existing = {p["slug"]: p for p in api.get("/projects?limit=200&offset=0")["items"]}
    if SLUG in existing:
        if not args.reset:
            print(f"'{SLUG}' already exists; use --reset to recreate it")
            return 1
        api.delete(f"/projects/{existing[SLUG]['id']}")
        print("removed the old project")
    builder = build(api)
    print(f"{len(bp.ENTITIES)} entities, {len(bp.RELATIONS)} relations, {len(bp.ROLES)} roles")
    ok = builder.report()
    if ok and not args.no_save:
        save(api, builder.id, HERE)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
