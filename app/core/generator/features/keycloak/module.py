"""The `keycloak` feature: a ready-to-import Keycloak realm and the script that registers this
project's clients and roles in a realm.

Only used when the project's auth provider is Keycloak. In `own` mode the zip ships
`keycloak/realm.json`, imported on Keycloak's first start. In `shared` mode the realm already
exists, so the zip ships only `keycloak/clients.json` and `scripts/keycloak_register.py`, which
add this project's clients and roles to it. Secrets are never rendered: the realm file refers to
environment variables with `${NAME}` placeholders that Keycloak fills in when it imports.
"""

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.core.generator.base import FileTree
from app.core.generator.context import ProjectCtx
from app.core.generator.render import read_verbatim
from app.core.spec_models import SpecAuth, SpecIdentityProvider, SpecKeycloak

_TEMPLATES = Path(__file__).parent / "templates"

# Pinned, never "latest": an audit needs to know exactly which version ships.
KEYCLOAK_IMAGE = "quay.io/keycloak/keycloak"
KEYCLOAK_IMAGE_TAG = "26.8.1"

# Where Swagger UI (/docs) of the API is reachable; filled from the environment at import time.
API_URL_PLACEHOLDER = "${API_PUBLIC_URL}"

# Keycloak's own list of required actions for KEYCLOAK_IMAGE_TAG. Importing a realm that names
# any required action replaces the whole list, so to change one we must restate all of them.
# (name, enabled, priority); re-check this list whenever the image tag changes.
_REQUIRED_ACTIONS: tuple[tuple[str, str, bool, int], ...] = (
    ("TERMS_AND_CONDITIONS", "Terms and Conditions", False, 20),
    ("UPDATE_PROFILE", "Update Profile", True, 40),
    ("VERIFY_EMAIL", "Verify Email", True, 50),
    ("CONFIGURE_TOTP", "Configure OTP", True, 54),
    ("UPDATE_PASSWORD", "Update Password", True, 57),
    ("delete_account", "Delete Account", False, 60),
    ("UPDATE_EMAIL", "Update Email", False, 70),
    ("webauthn-register", "Webauthn Register", True, 80),
    ("webauthn-register-passwordless", "Webauthn Register Passwordless", True, 90),
    ("VERIFY_PROFILE", "Verify Profile", True, 100),
    ("delete_credential", "Delete Credential", True, 110),
    ("idp_link", "Linking Identity Provider", True, 120),
    ("CONFIGURE_RECOVERY_AUTHN_CODES", "Recovery Authentication Codes", True, 130),
    ("update_user_locale", "Update User Locale", True, 1000),
)
# Second-factor setup actions: switched off entirely when MFA is off.
_SECOND_FACTOR_ACTIONS = frozenset(
    {
        "CONFIGURE_TOTP",
        "webauthn-register",
        "webauthn-register-passwordless",
        "CONFIGURE_RECOVERY_AUTHN_CODES",
    }
)

_FAILURE_FACTOR = 5
_PASSWORD_HISTORY = 5


def idp_secret_env(alias: str) -> str:
    """Environment variable that holds the client secret of identity provider `alias`."""
    return "KC_IDP_" + alias.upper().replace("-", "_") + "_CLIENT_SECRET"


def docs_client_id(kc: SpecKeycloak) -> str:
    return f"{kc.web_client_id}-docs"


def _origin(uri: str) -> str:
    parts = urlsplit(uri)
    return f"{parts.scheme}://{parts.netloc}"


def _app_name(project: ProjectCtx, auth: SpecAuth) -> str:
    return auth.app_name or project.name


def _role_names(auth: SpecAuth) -> list[str]:
    return sorted(r.name for r in auth.roles)


# --- clients ----------------------------------------------------------------------------


def _audience_mapper(kc: SpecKeycloak) -> dict[str, Any]:
    """Adds the API client to `aud` of every token, so a user with no roles yet still gets a
    token the API accepts (and a token for another project's API is not accepted here)."""
    return {
        "name": "api-audience",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper",
        "consentRequired": False,
        "config": {
            "included.client.audience": kc.api_client_id,
            "id.token.claim": "false",
            "access.token.claim": "true",
            "introspection.token.claim": "true",
        },
    }


def _browser_client(
    kc: SpecKeycloak,
    *,
    client_id: str,
    name: str,
    redirect_uris: list[str],
    web_origins: list[str],
) -> dict[str, Any]:
    """A public client for the authorization-code flow with PKCE (no secret, no password grant,
    no implicit flow) and only the roles of this project's API in its tokens."""
    return {
        "clientId": client_id,
        "name": name,
        "enabled": True,
        "protocol": "openid-connect",
        "publicClient": True,
        "standardFlowEnabled": True,
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "serviceAccountsEnabled": False,
        "fullScopeAllowed": False,
        "redirectUris": redirect_uris,
        "webOrigins": web_origins,
        "attributes": {
            "pkce.code.challenge.method": "S256",
            "post.logout.redirect.uris": "##".join(redirect_uris),
        },
        "protocolMappers": [_audience_mapper(kc)],
    }


def client_representations(
    project: ProjectCtx, auth: SpecAuth, kc: SpecKeycloak
) -> list[dict[str, Any]]:
    app = _app_name(project, auth)
    origins = sorted({_origin(u) for u in kc.redirect_uris})
    api = {
        "clientId": kc.api_client_id,
        "name": f"{app} API",
        "description": "The audience of this project's API tokens. Nobody signs in with it.",
        "enabled": True,
        "protocol": "openid-connect",
        "publicClient": False,
        "bearerOnly": False,
        "standardFlowEnabled": False,
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "serviceAccountsEnabled": False,
        "fullScopeAllowed": False,
    }
    web = _browser_client(
        kc,
        client_id=kc.web_client_id,
        name=f"{app} web",
        redirect_uris=list(kc.redirect_uris),
        web_origins=origins,
    )
    docs = _browser_client(
        kc,
        client_id=docs_client_id(kc),
        name=f"{app} API docs (Swagger UI)",
        redirect_uris=[f"{API_URL_PLACEHOLDER}/docs/oauth2-redirect"],
        web_origins=[API_URL_PLACEHOLDER],
    )
    return [api, web, docs]


def role_representations(auth: SpecAuth) -> list[dict[str, Any]]:
    return [
        {"name": r.name, "description": r.label, "composite": False, "clientRole": True}
        for r in sorted(auth.roles, key=lambda r: r.name)
    ]


# --- identity providers -----------------------------------------------------------------


def _idp_config(idp: SpecIdentityProvider, **extra: str) -> dict[str, str]:
    return {
        "clientId": idp.client_id,
        "clientSecret": "${" + idp_secret_env(idp.alias) + "}",
        "syncMode": "IMPORT",
        **extra,
    }


def _oidc_config(idp: SpecIdentityProvider, endpoints: dict[str, str]) -> dict[str, str]:
    return _idp_config(
        idp,
        **endpoints,
        validateSignature="true",
        useJwksUrl="true",
        clientAuthMethod="client_secret_post",
        defaultScope="openid profile email",
        pkceEnabled="true",
        pkceMethod="S256",
    )


def identity_provider_representation(idp: SpecIdentityProvider) -> dict[str, Any]:
    provider_id = "oidc"
    trust_email = False  # only a provider that verifies emails may be trusted to
    match idp.type:
        case "google":
            provider_id, trust_email = "google", True
            extra = {"defaultScope": "openid profile email"}
            if idp.hosted_domain:
                extra["hostedDomain"] = idp.hosted_domain
            config = _idp_config(idp, **extra)
        case "github":
            provider_id = "github"
            config = _idp_config(idp, defaultScope="user:email")
        case "microsoft":
            base = f"https://login.microsoftonline.com/{idp.tenant_id}"
            config = _oidc_config(
                idp,
                {
                    "issuer": f"{base}/v2.0",
                    "authorizationUrl": f"{base}/oauth2/v2.0/authorize",
                    "tokenUrl": f"{base}/oauth2/v2.0/token",
                    "jwksUrl": f"{base}/discovery/v2.0/keys",
                    "userInfoUrl": "https://graph.microsoft.com/oidc/userinfo",
                },
            )
        case _:
            endpoints = {
                "issuer": idp.issuer or "",
                "authorizationUrl": idp.authorization_url or "",
                "tokenUrl": idp.token_url or "",
                "jwksUrl": idp.jwks_url or "",
            }
            if idp.userinfo_url:
                endpoints["userInfoUrl"] = idp.userinfo_url
            config = _oidc_config(idp, endpoints)
    return {
        "alias": idp.alias,
        "displayName": idp.display_name or idp.alias,
        "providerId": provider_id,
        "enabled": True,
        "trustEmail": trust_email,
        "storeToken": False,
        "addReadTokenRoleOnCreate": False,
        "authenticateByDefault": False,
        "linkOnly": False,
        "firstBrokerLoginFlowAlias": "first broker login",
        "config": config,
    }


# --- realm ------------------------------------------------------------------------------


def _smtp(auth: SpecAuth) -> dict[str, str] | None:
    smtp = auth.smtp
    if smtp is None:
        return None
    implicit_ssl = smtp.use_tls and smtp.port == 465
    return {
        "host": smtp.host,
        "port": str(smtp.port),
        "from": smtp.from_email,
        "fromDisplayName": smtp.from_name,
        "auth": "true",
        "user": "${SMTP_USERNAME}",
        "password": "${SMTP_PASSWORD}",
        "ssl": "true" if implicit_ssl else "false",
        "starttls": "true" if smtp.use_tls and not implicit_ssl else "false",
    }


def _password_policy(kc: SpecKeycloak) -> str:
    return (
        f"length({kc.password_min_length}) and notUsername and notEmail "
        f"and passwordHistory({_PASSWORD_HISTORY})"
    )


def _required_actions(mfa: str) -> list[dict[str, Any]] | None:
    """The realm's required actions, or None to keep Keycloak's defaults (MFA optional)."""
    if mfa == "optional":
        return None
    actions = []
    for alias, name, enabled, priority in _REQUIRED_ACTIONS:
        if mfa == "off" and alias in _SECOND_FACTOR_ACTIONS:
            enabled = False
        actions.append(
            {
                "alias": alias,
                "name": name,
                "providerId": alias,
                "enabled": enabled,
                # "required": every user must set up an authenticator at their first sign-in.
                "defaultAction": mfa == "required" and alias == "CONFIGURE_TOTP",
                "priority": priority,
            }
        )
    return actions


def realm_representation(project: ProjectCtx, auth: SpecAuth, kc: SpecKeycloak) -> dict[str, Any]:
    """The realm Keycloak imports on its first start (own mode)."""
    names = _role_names(auth)
    realm: dict[str, Any] = {
        "realm": kc.realm,
        "displayName": _app_name(project, auth),
        "enabled": True,
        # Plain http is accepted only from private addresses; the public URL must be https.
        "sslRequired": "external",
        "registrationAllowed": not auth.registration.invite_only,
        "registrationEmailAsUsername": True,
        "loginWithEmailAllowed": True,
        "duplicateEmailsAllowed": False,
        "editUsernameAllowed": False,
        "rememberMe": False,
        "verifyEmail": auth.registration.email_verification_required,
        "resetPasswordAllowed": auth.smtp is not None,
        "passwordPolicy": _password_policy(kc),
        # Lock out guessing, with growing waits rather than a permanent lock an attacker could
        # use to lock real users out.
        "bruteForceProtected": True,
        "permanentLockout": False,
        "failureFactor": _FAILURE_FACTOR,
        "waitIncrementSeconds": 60,
        "maxFailureWaitSeconds": 900,
        "minimumQuickLoginWaitSeconds": 60,
        "quickLoginCheckMilliSeconds": 1000,
        "maxDeltaTimeSeconds": 43200,
        # Short-lived access tokens; refresh tokens rotate and cannot be replayed.
        "accessTokenLifespan": auth.access_token_ttl_minutes * 60,
        "ssoSessionIdleTimeout": kc.session_idle_minutes * 60,
        "ssoSessionMaxLifespan": kc.session_max_hours * 3600,
        "accessCodeLifespan": 60,
        "revokeRefreshToken": True,
        "refreshTokenMaxReuse": 0,
        "defaultSignatureAlgorithm": "RS256",
        # An audit trail of sign-ins and of every change an admin makes.
        "eventsEnabled": True,
        "eventsExpiration": kc.audit_retention_days * 86400,
        "eventsListeners": ["jboss-logging"],
        "adminEventsEnabled": True,
        "adminEventsDetailsEnabled": True,
        "browserSecurityHeaders": {
            "contentSecurityPolicy": "frame-src 'self'; frame-ancestors 'self'; object-src 'none';",
            "contentSecurityPolicyReportOnly": "",
            "xContentTypeOptions": "nosniff",
            "xRobotsTag": "none",
            "xFrameOptions": "SAMEORIGIN",
            "xXSSProtection": "1; mode=block",
            "strictTransportSecurity": "max-age=31536000; includeSubDomains",
            "referrerPolicy": "no-referrer",
        },
        "roles": {"client": {kc.api_client_id: role_representations(auth)}},
        "clients": client_representations(project, auth, kc),
        "identityProviders": [
            identity_provider_representation(i)
            for i in sorted(kc.identity_providers, key=lambda i: i.alias)
        ],
    }
    if names:
        realm["clientScopeMappings"] = {
            kc.api_client_id: [
                {"client": kc.web_client_id, "roles": names},
                {"client": docs_client_id(kc), "roles": names},
            ]
        }
    smtp = _smtp(auth)
    if smtp is not None:
        realm["smtpServer"] = smtp
    required_actions = _required_actions(kc.mfa)
    if required_actions is not None:
        realm["requiredActions"] = required_actions
    return realm


def clients_document(project: ProjectCtx, auth: SpecAuth, kc: SpecKeycloak) -> dict[str, Any]:
    """What scripts/keycloak_register.py adds to a realm (own or shared)."""
    return {
        "realm": kc.realm,
        "api_client_id": kc.api_client_id,
        "browser_client_ids": [kc.web_client_id, docs_client_id(kc)],
        "clients": client_representations(project, auth, kc),
        "roles": role_representations(auth),
    }


def _dump(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, ensure_ascii=True) + "\n"


class KeycloakModule:
    name = "keycloak"

    def render(self, project: ProjectCtx) -> FileTree:
        auth = project.auth
        if auth is None or auth.provider != "keycloak" or auth.keycloak is None:
            return {}
        kc = auth.keycloak
        files: FileTree = {
            "keycloak/clients.json": _dump(clients_document(project, auth, kc)),
            "scripts/keycloak_register.py": read_verbatim(_TEMPLATES, "keycloak_register.py.tpl"),
        }
        if kc.mode == "own":
            files["keycloak/realm.json"] = _dump(realm_representation(project, auth, kc))
        return files
