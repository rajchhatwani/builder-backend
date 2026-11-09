"""Suite identity, path (a): a NEW project that joins a suite is generated as a member of a shared
Keycloak realm.

A suite is a set of projects that share one sign-in. For a new project the realm is not free text:
it is derived as `suite-<suite_id>`. The project registers ONE client named after its slug in that
realm, with its roles as client roles, and accepts only tokens whose issuer is the suite realm and
whose `aud` contains its own client id (suite-wide sign-in, per-app authorization).
"""

from app.core.spec_models import Spec, SpecKeycloak

SUITE_REALM_PREFIX = "suite-"
# Keycloak realm names are at most 63 characters (see the realm rule in validation).
MAX_SUITE_ID_LENGTH = 63 - len(SUITE_REALM_PREFIX)
JOIN_STATES = ("none", "planned", "joined")
# The realm-level client scope whose audience mappers list every member of the suite.
AUDIENCE_SCOPE = "suite-audience"


def suite_realm(suite_id: str) -> str:
    return f"{SUITE_REALM_PREFIX}{suite_id}"


def hub_base_url(hub_issuer: str) -> str:
    """The Keycloak address (no realm path) of a hub issuer such as https://id.acme.com/realms/x."""
    return hub_issuer.rstrip("/").rsplit("/realms/", 1)[0]


def effective_keycloak(spec: Spec) -> SpecKeycloak | None:
    """The Keycloak block the generator works from. For a suite member the realm, the mode and
    the client ids are derived (never taken from the stored block); everything else is kept."""
    auth = spec.auth
    if auth is None or auth.keycloak is None or auth.suite is None:
        return None
    slug = spec.project.slug
    return auth.keycloak.model_copy(
        update={
            "mode": "shared",
            "realm": suite_realm(auth.suite.suite_id),
            "api_client_id": slug,
            "web_client_id": slug,
            # The hub owns the identity providers.
            "identity_providers": [],
        }
    )


def apply_suite(spec: Spec) -> Spec:
    """The spec with the derived Keycloak block, or the same spec when it is not a suite member."""
    auth = spec.auth
    if auth is None or auth.provider != "keycloak" or auth.suite is None:
        return spec
    effective = effective_keycloak(spec)
    if effective is None:
        return spec
    return spec.model_copy(update={"auth": auth.model_copy(update={"keycloak": effective})})
