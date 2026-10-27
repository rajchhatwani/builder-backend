"""SAML 2.0 service-provider side: AuthnRequest (HTTP-Redirect), SP metadata, and Response
validation (HTTP-POST). Pure functions: no database, no HTTP.

Validation follows the usual SP checklist (OASIS SAML profiles §4.1.4, and the step SSOJet flags
as security-critical in PLATFORM_SAAS_PLAN §4.2):
  - no DTDs or entities in the input (XXE, entity expansion);
  - exactly one plain Assertion (EncryptedAssertion is refused with a clear reason);
  - an enveloped XML signature, by the configured IdP certificate, over the Response or the
    Assertion; every value is then read from the *signed* subtree that `signxml` hands back, never
    from the original document, which is what defeats signature wrapping;
  - Issuer, Audience, Recipient, the Conditions and SubjectConfirmation time windows;
  - `InResponseTo` is returned so the caller can match it to a login it started (one use only).
"""

import base64
import binascii
import hashlib
import secrets
import urllib.parse
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from lxml import etree
from signxml.algorithms import DigestAlgorithm, SignatureMethod
from signxml.exceptions import InvalidInput, InvalidSignature
from signxml.verifier import SignatureConfiguration, XMLVerifier

NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
    "md": "urn:oasis:names:tc:SAML:2.0:metadata",
}
_SUCCESS = "urn:oasis:names:tc:SAML:2.0:status:Success"
_BEARER = "urn:oasis:names:tc:SAML:2.0:cm:bearer"
_POST_BINDING = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
_EMAIL_FORMAT = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
MAX_RESPONSE_BYTES = 256 * 1024

# Attribute names IdPs use for the e-mail address (Okta, Entra ID / ADFS, Google, OneLogin...).
_EMAIL_ATTRIBUTES = (
    "email",
    "mail",
    "emailaddress",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
    "urn:oid:0.9.2342.19200300.100.1.3",
    "user.email",
)
_FIRST_NAME_ATTRIBUTES = (
    "firstname",
    "givenname",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname",
    "urn:oid:2.5.4.42",
)
_LAST_NAME_ATTRIBUTES = (
    "lastname",
    "surname",
    "sn",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/surname",
    "urn:oid:2.5.4.4",
)
_DISPLAY_NAME_ATTRIBUTES = (
    "displayname",
    "name",
    "http://schemas.microsoft.com/identity/claims/displayname",
)

# Asymmetric only: an HMAC "signature" would need a shared secret we never configure. SHA-1 is out.
_SIGNATURE_METHODS = frozenset(
    {
        SignatureMethod.RSA_SHA256,
        SignatureMethod.RSA_SHA384,
        SignatureMethod.RSA_SHA512,
        SignatureMethod.SHA256_RSA_MGF1,
        SignatureMethod.SHA384_RSA_MGF1,
        SignatureMethod.SHA512_RSA_MGF1,
        SignatureMethod.ECDSA_SHA256,
        SignatureMethod.ECDSA_SHA384,
        SignatureMethod.ECDSA_SHA512,
    }
)
_DIGESTS = frozenset({DigestAlgorithm.SHA256, DigestAlgorithm.SHA384, DigestAlgorithm.SHA512})


class SamlError(Exception):
    """`reason` is a short code for audit and the login error page; never echo IdP content."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SamlIdentity:
    email: str
    name: str
    name_id: str
    in_response_to: str


# -- SP side ---------------------------------------------------------------------------------


def new_request_id() -> str:
    """An xs:ID (must not start with a digit): '_' + 128 random bits in hex."""
    return "_" + secrets.token_hex(16)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def authn_request_url(
    *,
    sp_entity_id: str,
    acs_url: str,
    idp_sso_url: str,
    request_id: str,
    now: datetime | None = None,
) -> str:
    """HTTP-Redirect binding: deflate + base64 + URL-encode an unsigned AuthnRequest."""
    issued = _iso(now or datetime.now(UTC))
    xml = (
        f'<samlp:AuthnRequest xmlns:samlp="{NS["samlp"]}" xmlns:saml="{NS["saml"]}"'
        f' ID={quoteattr(request_id)} Version="2.0" IssueInstant={quoteattr(issued)}'
        f" Destination={quoteattr(idp_sso_url)} AssertionConsumerServiceURL={quoteattr(acs_url)}"
        f" ProtocolBinding={quoteattr(_POST_BINDING)}>"
        f"<saml:Issuer>{escape(sp_entity_id)}</saml:Issuer>"
        f'<samlp:NameIDPolicy Format="{_EMAIL_FORMAT}" AllowCreate="true"/>'
        "</samlp:AuthnRequest>"
    )
    compressor = zlib.compressobj(wbits=-15)
    deflated = compressor.compress(xml.encode()) + compressor.flush()
    query = urllib.parse.urlencode({"SAMLRequest": base64.b64encode(deflated).decode()})
    separator = "&" if urllib.parse.urlparse(idp_sso_url).query else "?"
    return f"{idp_sso_url}{separator}{query}"


def sp_metadata(*, sp_entity_id: str, acs_url: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<md:EntityDescriptor xmlns:md="{NS["md"]}" entityID={quoteattr(sp_entity_id)}>'
        '<md:SPSSODescriptor AuthnRequestsSigned="false" WantAssertionsSigned="true"'
        ' protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
        f"<md:NameIDFormat>{_EMAIL_FORMAT}</md:NameIDFormat>"
        f'<md:AssertionConsumerService Binding="{_POST_BINDING}"'
        f' Location={quoteattr(acs_url)} index="0" isDefault="true"/>'
        "</md:SPSSODescriptor></md:EntityDescriptor>\n"
    )


# -- certificates ----------------------------------------------------------------------------


def normalize_cert(text: str) -> str:
    """Accept a PEM block or the bare base64 IdPs often show; return canonical PEM."""
    body = text.strip()
    if "BEGIN CERTIFICATE" not in body:
        body = "-----BEGIN CERTIFICATE-----\n" + body + "\n-----END CERTIFICATE-----"
    try:
        cert = x509.load_pem_x509_certificate(body.encode())
    except ValueError as exc:
        raise SamlError("invalid_certificate") from exc
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def cert_summary(pem: str) -> dict[str, str]:
    """What the UI may show about the IdP certificate: never the certificate itself in audit."""
    cert = x509.load_pem_x509_certificate(pem.encode())
    digest = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest().upper()
    return {
        "sha256_fingerprint": ":".join(digest[i : i + 2] for i in range(0, len(digest), 2)),
        "not_after": cert.not_valid_after_utc.isoformat(),
        "subject": cert.subject.rfc4514_string()[:200],
    }


# -- Response validation ---------------------------------------------------------------------

_PARSER = etree.XMLParser(
    resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False, remove_pis=True
)


def _parse(raw: bytes) -> Any:
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise SamlError("malformed")
    try:
        root = etree.fromstring(raw, parser=_PARSER)
    except etree.XMLSyntaxError as exc:
        raise SamlError("malformed") from exc
    return root


def _decode(saml_response: str) -> bytes:
    if len(saml_response) > MAX_RESPONSE_BYTES * 4 // 3 + 4:
        raise SamlError("too_large")
    try:
        raw = base64.b64decode(saml_response, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise SamlError("malformed") from exc
    if not raw or len(raw) > MAX_RESPONSE_BYTES:
        raise SamlError("malformed")
    return raw


def _verify(data: Any, cert_pem: str) -> Any:
    """Verify an enveloped signature that is a direct child of `data`; return the signed element."""
    config = SignatureConfiguration(
        require_x509=True,
        location="./",
        expect_references=1,
        signature_methods=_SIGNATURE_METHODS,
        digest_algorithms=_DIGESTS,
    )
    try:
        result = XMLVerifier().verify(
            data, x509_cert=cert_pem, parser=_PARSER, expect_config=config, id_attribute="ID"
        )
    except (InvalidSignature, InvalidInput, etree.XMLSyntaxError, ValueError) as exc:
        raise SamlError("bad_signature") from exc
    if isinstance(result, list):  # only when several references are expected
        raise SamlError("bad_signature")
    return result.signed_xml


def _time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SamlError("malformed") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _text(el: Any) -> str:
    return (el.text or "").strip() if el is not None else ""


def validate_response(
    saml_response: str,
    *,
    idp_cert_pem: str,
    idp_entity_id: str,
    sp_entity_id: str,
    acs_url: str,
    now: datetime | None = None,
    skew_seconds: int = 120,
) -> SamlIdentity:
    root = _parse(_decode(saml_response))
    if root.tag != f"{{{NS['samlp']}}}Response":
        raise SamlError("malformed")
    if root.findall(".//saml:EncryptedAssertion", NS):
        raise SamlError("encrypted_assertion_unsupported")
    if len(root.findall(".//saml:Assertion", NS)) != 1:
        raise SamlError(
            "multiple_assertions" if root.findall(".//saml:Assertion", NS) else "no_assertion"
        )

    status = root.find("samlp:Status/samlp:StatusCode", NS)
    response_signed = root.find("ds:Signature", NS) is not None
    assertion = root.find("saml:Assertion", NS)
    if assertion is None:  # the only Assertion is nested somewhere it shouldn't be
        raise SamlError("malformed")
    assertion_signed = assertion.find("ds:Signature", NS) is not None

    if response_signed:
        signed_response = _verify(root, idp_cert_pem)
        signed_assertion = signed_response.find("saml:Assertion", NS)
        status = signed_response.find("samlp:Status/samlp:StatusCode", NS)
        destination = signed_response.get("Destination")
        if signed_assertion is None:
            raise SamlError("no_assertion")
    elif assertion_signed:
        signed_assertion = _verify(etree.tostring(assertion), idp_cert_pem)
        destination = root.get("Destination")
    else:
        raise SamlError("unsigned")

    if status is None or status.get("Value") != _SUCCESS:
        raise SamlError("idp_status")
    if destination and destination != acs_url:
        raise SamlError("wrong_recipient")

    current = now or datetime.now(UTC)
    skew = timedelta(seconds=skew_seconds)

    if _text(signed_assertion.find("saml:Issuer", NS)) != idp_entity_id:
        raise SamlError("wrong_issuer")

    conditions = signed_assertion.find("saml:Conditions", NS)
    if conditions is None:
        raise SamlError("malformed")
    not_before = _time(conditions.get("NotBefore"))
    not_after = _time(conditions.get("NotOnOrAfter"))
    if not_before is not None and current + skew < not_before:
        raise SamlError("not_yet_valid")
    if not_after is None or current - skew >= not_after:
        raise SamlError("expired")
    audiences = [_text(a) for a in conditions.findall("saml:AudienceRestriction/saml:Audience", NS)]
    if sp_entity_id not in audiences:
        raise SamlError("wrong_audience")

    subject = signed_assertion.find("saml:Subject", NS)
    if subject is None:
        raise SamlError("malformed")
    in_response_to = ""
    confirmed = False
    for confirmation in subject.findall("saml:SubjectConfirmation", NS):
        if confirmation.get("Method") != _BEARER:
            continue
        data = confirmation.find("saml:SubjectConfirmationData", NS)
        if data is None:
            continue
        if data.get("Recipient") != acs_url:
            raise SamlError("wrong_recipient")
        until = _time(data.get("NotOnOrAfter"))
        if until is None or current - skew >= until:
            raise SamlError("expired")
        in_response_to = data.get("InResponseTo") or ""
        confirmed = True
        break
    if not confirmed:
        raise SamlError("no_bearer_confirmation")
    if not in_response_to:
        raise SamlError("unsolicited")  # IdP-initiated login is refused (no InResponseTo)
    if root.get("InResponseTo") and root.get("InResponseTo") != in_response_to:
        raise SamlError("wrong_in_response_to")

    name_id_el = subject.find("saml:NameID", NS)
    name_id = _text(name_id_el)
    attributes: dict[str, str] = {}
    for attr in signed_assertion.findall("saml:AttributeStatement/saml:Attribute", NS):
        value = _text(attr.find("saml:AttributeValue", NS))
        if value:
            attributes[(attr.get("Name") or "").lower()] = value

    email = next((attributes[a] for a in _EMAIL_ATTRIBUTES if a in attributes), "")
    if not email and "@" in name_id:
        email = name_id
    email = email.strip().lower()
    if not email or "@" not in email or len(email) > 254:
        raise SamlError("no_email")

    display = next((attributes[a] for a in _DISPLAY_NAME_ATTRIBUTES if a in attributes), "")
    if not display:
        first = next((attributes[a] for a in _FIRST_NAME_ATTRIBUTES if a in attributes), "")
        last = next((attributes[a] for a in _LAST_NAME_ATTRIBUTES if a in attributes), "")
        display = f"{first} {last}".strip()
    return SamlIdentity(
        email=email, name=display[:100], name_id=name_id[:255], in_response_to=in_response_to
    )
