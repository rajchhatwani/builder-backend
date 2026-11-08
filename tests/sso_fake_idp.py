"""A tiny identity provider for tests: a self-signed key pair that signs SAML Responses (like Okta /
Entra ID do) and OIDC ID tokens (RS256, with a JWKS). Nothing here is used by the app."""

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree
from signxml import XMLSigner

IDP_ENTITY_ID = "https://idp.example.test/saml/metadata"
IDP_SSO_URL = "https://idp.example.test/saml/sso"


class KeyPair:
    def __init__(self, cn: str) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(UTC)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
        self.cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(self.key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=365))
            .sign(self.key, hashes.SHA256())
        )
        self.key_pem = self.key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        self.cert_pem = self.cert.public_bytes(serialization.Encoding.PEM).decode()


@lru_cache
def idp_keys() -> KeyPair:
    return KeyPair("Test IdP")


@lru_cache
def attacker_keys() -> KeyPair:
    return KeyPair("Attacker")


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def saml_response_xml(
    *,
    email: str,
    sp_entity_id: str,
    acs_url: str,
    in_response_to: str,
    issuer: str = IDP_ENTITY_ID,
    audience: str | None = None,
    recipient: str | None = None,
    now: datetime | None = None,
    not_before: datetime | None = None,
    not_on_or_after: datetime | None = None,
    status: str = "urn:oasis:names:tc:SAML:2.0:status:Success",
    name_id_in_attribute: bool = False,
    first_name: str = "Alice",
    last_name: str = "Smith",
) -> str:
    now = now or datetime.now(UTC)
    nb = not_before or now - timedelta(minutes=1)
    noa = not_on_or_after or now + timedelta(minutes=5)
    rid, aid = f"_r{uuid.uuid4().hex}", f"_a{uuid.uuid4().hex}"
    name_id = (
        f'<saml:NameID Format="urn:oasis:names:tc:SAML:2.0:nameid-format:persistent">'
        f"00u{uuid.uuid4().hex[:10]}</saml:NameID>"
        if name_id_in_attribute
        else f'<saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">'
        f"{email}</saml:NameID>"
    )
    email_attr = (
        '<saml:Attribute Name="http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress">'
        f"<saml:AttributeValue>{email}</saml:AttributeValue></saml:Attribute>"
        if name_id_in_attribute
        else ""
    )
    return f"""<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
 xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="{rid}" Version="2.0"
 IssueInstant="{_iso(now)}" Destination="{recipient or acs_url}" InResponseTo="{in_response_to}">
<saml:Issuer>{issuer}</saml:Issuer>
<samlp:Status><samlp:StatusCode Value="{status}"/></samlp:Status>
<saml:Assertion ID="{aid}" Version="2.0" IssueInstant="{_iso(now)}">
<saml:Issuer>{issuer}</saml:Issuer>
<saml:Subject>{name_id}
<saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">
<saml:SubjectConfirmationData InResponseTo="{in_response_to}" NotOnOrAfter="{_iso(noa)}"
 Recipient="{recipient or acs_url}"/>
</saml:SubjectConfirmation></saml:Subject>
<saml:Conditions NotBefore="{_iso(nb)}" NotOnOrAfter="{_iso(noa)}">
<saml:AudienceRestriction><saml:Audience>{audience or sp_entity_id}</saml:Audience>
</saml:AudienceRestriction></saml:Conditions>
<saml:AuthnStatement AuthnInstant="{_iso(now)}"><saml:AuthnContext>
<saml:AuthnContextClassRef>urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport</saml:AuthnContextClassRef>
</saml:AuthnContext></saml:AuthnStatement>
<saml:AttributeStatement>{email_attr}
<saml:Attribute Name="firstName">
<saml:AttributeValue>{first_name}</saml:AttributeValue></saml:Attribute>
<saml:Attribute Name="lastName">
<saml:AttributeValue>{last_name}</saml:AttributeValue></saml:Attribute>
</saml:AttributeStatement>
</saml:Assertion></samlp:Response>"""


_NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
}


def _signer() -> XMLSigner:
    return XMLSigner(c14n_algorithm="http://www.w3.org/2001/10/xml-exc-c14n#")


def sign_assertion(xml: str, keys: KeyPair | None = None) -> str:
    """Sign the Assertion (the common IdP default) and put it back in the Response."""
    keys = keys or idp_keys()
    root = etree.fromstring(xml.encode())
    assertion = root.find("saml:Assertion", _NS)
    assert assertion is not None
    signed = _signer().sign(
        assertion,
        key=keys.key_pem,
        cert=keys.cert_pem,
        reference_uri="#" + assertion.get("ID"),
        id_attribute="ID",
    )
    root.replace(assertion, signed)
    return etree.tostring(root).decode()


def sign_response(xml: str, keys: KeyPair | None = None) -> str:
    """Sign the whole Response instead (some IdPs, e.g. ADFS when configured so)."""
    keys = keys or idp_keys()
    root = etree.fromstring(xml.encode())
    signed = _signer().sign(
        root,
        key=keys.key_pem,
        cert=keys.cert_pem,
        reference_uri="#" + root.get("ID"),
        id_attribute="ID",
    )
    return etree.tostring(signed).decode()


def b64(xml: str) -> str:
    return base64.b64encode(xml.encode()).decode()


# -- OIDC -------------------------------------------------------------------------------------

OIDC_ISSUER = "https://login.oidc.example.test"
OIDC_DISCOVERY_URL = OIDC_ISSUER + "/.well-known/openid-configuration"
OIDC_KID = "test-key-1"


def discovery_document() -> dict[str, Any]:
    return {
        "issuer": OIDC_ISSUER,
        "authorization_endpoint": OIDC_ISSUER + "/authorize",
        "token_endpoint": OIDC_ISSUER + "/token",
        "jwks_uri": OIDC_ISSUER + "/jwks",
        "id_token_signing_alg_values_supported": ["RS256"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
    }


def jwks(keys: KeyPair | None = None) -> dict[str, Any]:
    keys = keys or idp_keys()
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(keys.key.public_key()))
    jwk.update({"kid": OIDC_KID, "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}


def id_token(
    *,
    client_id: str,
    nonce: str,
    email: str,
    issuer: str = OIDC_ISSUER,
    audience: str | None = None,
    email_verified: bool | None = True,
    expires_in: int = 300,
    keys: KeyPair | None = None,
    kid: str = OIDC_KID,
    algorithm: str = "RS256",
    extra: dict[str, Any] | None = None,
) -> str:
    keys = keys or idp_keys()
    now = int(datetime.now(UTC).timestamp())
    claims: dict[str, Any] = {
        "iss": issuer,
        "aud": audience or client_id,
        "sub": "user-" + email,
        "iat": now,
        "exp": now + expires_in,
        "nonce": nonce,
        "email": email,
        "name": "Alice Smith",
    }
    if email_verified is not None:
        claims["email_verified"] = email_verified
    claims.update(extra or {})
    return jwt.encode(claims, keys.key_pem, algorithm=algorithm, headers={"kid": kid})
