"""OpenID Connect relying-party side: discovery, authorization-code flow with PKCE (S256), code
exchange and ID token validation. No database.

Every URL the server fetches came from an org admin's form (the discovery URL) or from the
document behind it, so each one goes through `check_outbound_url` first: https only (unless
the deployment opts out for local work), no credentials in the URL, and the host must not resolve to
a private, loopback, link-local or metadata address unless the deployment allows self-hosted IdPs
on its own network (`BUILDER_SSO_ALLOW_PRIVATE_IDP`). Redirects are never followed.

ID tokens: asymmetric algorithms only (an `HS*` token signed with the public key, or `none`, is
refused before any key is touched), key chosen by `kid` from the IdP's JWKS, and `iss`, `aud`,
`exp`, `iat`, `nonce` all required.
"""

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import secrets
import socket
import urllib.parse
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

ALLOWED_ALGORITHMS = frozenset(
    {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"}
)
_TIMEOUT = httpx.Timeout(10.0)
_MAX_BYTES = 512 * 1024
LEEWAY_SECONDS = 60

# Tests replace this with an httpx.MockTransport.
TRANSPORT: httpx.AsyncBaseTransport | None = None


class OidcError(Exception):
    """`reason` is a short code for audit and the login error page."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Discovery:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    auth_methods: tuple[str, ...]

    @classmethod
    def from_document(cls, doc: Any) -> "Discovery":
        if not isinstance(doc, dict):
            raise OidcError("discovery_failed")
        try:
            fields = {
                k: doc[k]
                for k in ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri")
            }
        except KeyError as exc:
            raise OidcError("discovery_failed") from exc
        if not all(isinstance(v, str) and v for v in fields.values()):
            raise OidcError("discovery_failed")
        methods = doc.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
        return cls(**fields, auth_methods=tuple(m for m in methods if isinstance(m, str)))


@dataclass(frozen=True)
class OidcIdentity:
    email: str
    name: str
    subject: str


# -- outbound URL guard -----------------------------------------------------------------------


async def _resolve(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


async def check_outbound_url(url: str, *, allow_private: bool, require_https: bool) -> list[str]:
    """Refuse unsafe URLs. Returns the checked public addresses (empty when private hosts are
    allowed), which the caller connects to so DNS can't change its answer in between."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError as exc:
        raise OidcError("invalid_url") from exc
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise OidcError("invalid_url")
    if parts.username or parts.password:
        raise OidcError("invalid_url")
    if parts.scheme != "https" and require_https:
        raise OidcError("insecure_url")
    if allow_private:
        return []
    host = parts.hostname
    try:
        addresses = [host] if _is_ip(host) else await _resolve(host)
    except OSError as exc:
        raise OidcError("unresolvable_host") from exc
    if not addresses:
        raise OidcError("unresolvable_host")
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if not ip.is_global or ip.is_multicast:
            raise OidcError("private_address")
    return addresses


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


async def _request(
    method: str, url: str, *, allow_private: bool, require_https: bool, **kwargs: Any
) -> httpx.Response:
    addresses = await check_outbound_url(
        url, allow_private=allow_private, require_https=require_https
    )
    if addresses and TRANSPORT is None:
        # Connect to the address that was checked (a second lookup could be answered with an
        # internal one); the Host header and TLS name stay those of the real host.
        parts = urllib.parse.urlsplit(url)
        ip = addresses[0].split("%", 1)[0]
        host = f"[{ip}]" if ":" in ip else ip
        netloc = host if parts.port is None else f"{host}:{parts.port}"
        kwargs["headers"] = {**kwargs.get("headers", {}), "Host": parts.netloc.rpartition("@")[2]}
        kwargs["extensions"] = {"sni_hostname": parts.hostname}
        url = urllib.parse.urlunsplit(parts._replace(netloc=netloc))
    async with httpx.AsyncClient(
        transport=TRANSPORT, timeout=_TIMEOUT, follow_redirects=False
    ) as client:
        response = await client.request(method, url, **kwargs)
    if len(response.content) > _MAX_BYTES:
        raise OidcError("response_too_large")
    return response


def _json(response: httpx.Response, reason: str) -> Any:
    if response.status_code != 200:
        raise OidcError(reason)
    try:
        return response.json()
    except ValueError as exc:
        raise OidcError(reason) from exc


# -- flow ------------------------------------------------------------------------------------


async def fetch_discovery(url: str, *, allow_private: bool, require_https: bool) -> Discovery:
    try:
        response = await _request(
            "GET", url, allow_private=allow_private, require_https=require_https
        )
    except httpx.HTTPError as exc:
        raise OidcError("discovery_failed") from exc
    discovery = Discovery.from_document(_json(response, "discovery_failed"))
    for endpoint in (
        discovery.authorization_endpoint,
        discovery.token_endpoint,
        discovery.jwks_uri,
    ):
        if require_https and not endpoint.startswith("https://"):
            raise OidcError("insecure_url")
    return discovery


async def fetch_jwks(
    discovery: Discovery, *, allow_private: bool, require_https: bool
) -> dict[str, Any]:
    try:
        response = await _request(
            "GET", discovery.jwks_uri, allow_private=allow_private, require_https=require_https
        )
    except httpx.HTTPError as exc:
        raise OidcError("jwks_failed") from exc
    keys = _json(response, "jwks_failed")
    if not isinstance(keys, dict) or not isinstance(keys.get("keys"), list):
        raise OidcError("jwks_failed")
    return keys


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)  # 64 chars, within RFC 7636's 43..128
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.rstrip(b"=").decode()


def authorization_url(
    discovery: Discovery,
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    nonce: str,
    code_challenge: str,
    login_hint: str | None = None,
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if login_hint:
        params["login_hint"] = login_hint
    endpoint = discovery.authorization_endpoint
    separator = "&" if urllib.parse.urlsplit(endpoint).query else "?"
    return f"{endpoint}{separator}{urllib.parse.urlencode(params)}"


async def exchange_code(
    discovery: Discovery,
    *,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code_verifier: str,
    allow_private: bool,
    require_https: bool,
) -> str:
    """Return the raw ID token. client_secret_basic unless the IdP only lists _post."""
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }
    headers = {"Accept": "application/json"}
    if (
        "client_secret_basic" not in discovery.auth_methods
        and "client_secret_post" in discovery.auth_methods
    ):
        form |= {"client_id": client_id, "client_secret": client_secret}
    else:
        # RFC 6749 §2.3.1: form-encode both parts before joining them.
        user = urllib.parse.quote(client_id, safe="")
        password = urllib.parse.quote(client_secret, safe="")
        basic = base64.b64encode(f"{user}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {basic}"
    try:
        response = await _request(
            "POST",
            discovery.token_endpoint,
            allow_private=allow_private,
            require_https=require_https,
            data=form,
            headers=headers,
        )
    except httpx.HTTPError as exc:
        raise OidcError("token_exchange_failed") from exc
    body = _json(response, "token_exchange_failed")
    token = body.get("id_token") if isinstance(body, dict) else None
    if not isinstance(token, str) or not token:
        raise OidcError("no_id_token")
    return token


def verify_id_token(
    token: str,
    *,
    jwks: dict[str, Any],
    issuer: str,
    client_id: str,
    nonce: str,
    trust_unverified_email: bool = False,
) -> OidcIdentity:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise OidcError("bad_id_token") from exc
    alg = header.get("alg")
    if alg not in ALLOWED_ALGORITHMS:
        raise OidcError("unsupported_alg")
    keys = [k for k in jwks.get("keys", []) if isinstance(k, dict)]
    kid = header.get("kid")
    matching = [k for k in keys if k.get("kid") == kid] if kid else keys
    if len(matching) != 1:
        raise OidcError("unknown_key")
    try:
        key = jwt.PyJWK(matching[0], algorithm=alg)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=[alg],
            audience=client_id,
            issuer=issuer,
            leeway=LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise OidcError("bad_id_token") from exc
    aud = claims.get("aud")
    if isinstance(aud, list) and len(aud) > 1 and claims.get("azp") != client_id:
        raise OidcError("bad_id_token")
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise OidcError("wrong_nonce")
    verified = claims.get("email_verified")
    if verified in (False, "false") or (verified is None and not trust_unverified_email):
        raise OidcError("email_not_verified")
    email = claims.get("email")
    if not isinstance(email, str) or "@" not in email or len(email) > 254:
        raise OidcError("no_email")
    name = claims.get("name") or " ".join(
        str(claims.get(k, "")) for k in ("given_name", "family_name")
    )
    return OidcIdentity(
        email=email.strip().lower(), name=str(name).strip()[:100], subject=str(claims["sub"])
    )
