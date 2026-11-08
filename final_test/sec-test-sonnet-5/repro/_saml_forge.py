"""Build synthetic SAML Responses to drive the app's real ACS endpoint as a hostile IdP would.
Requires `uv run` (signxml/lxml/cryptography are project deps, not on system python3).
"""
from __future__ import annotations

import base64
import secrets
from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree
from signxml import XMLSigner

NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
}


def new_keypair(common_name: str = "sectest-synthetic-idp"):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    return key_pem, cert_pem


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_response_xml(
    *,
    idp_entity_id: str,
    sp_entity_id: str,
    acs_url: str,
    email: str,
    in_response_to: str,
    not_before_delta=timedelta(minutes=-5),
    not_after_delta=timedelta(minutes=5),
    recipient: str | None = None,
    destination: str | None = None,
    unsolicited: bool = False,
    extra_assertion_xml: str = "",
) -> tuple[str, str]:
    """Returns (response_xml, assertion_id) for the UNSIGNED document; sign it afterwards."""
    now = datetime.now(UTC)
    response_id = "_" + secrets.token_hex(16)
    assertion_id = "_" + secrets.token_hex(16)
    recipient = recipient if recipient is not None else acs_url
    destination = destination if destination is not None else acs_url
    irt_attr = "" if unsolicited else f' InResponseTo="{in_response_to}"'
    assertion = f"""
<saml:Assertion xmlns:saml="{NS['saml']}" ID="{assertion_id}" Version="2.0" IssueInstant="{_iso(now)}">
  <saml:Issuer>{idp_entity_id}</saml:Issuer>
  <saml:Subject>
    <saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">{email}</saml:NameID>
    <saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">
      <saml:SubjectConfirmationData NotOnOrAfter="{_iso(now + timedelta(minutes=5))}" Recipient="{recipient}"{irt_attr}/>
    </saml:SubjectConfirmation>
  </saml:Subject>
  <saml:Conditions NotBefore="{_iso(now + not_before_delta)}" NotOnOrAfter="{_iso(now + not_after_delta)}">
    <saml:AudienceRestriction><saml:Audience>{sp_entity_id}</saml:Audience></saml:AudienceRestriction>
  </saml:Conditions>
  <saml:AttributeStatement>
    <saml:Attribute Name="email"><saml:AttributeValue>{email}</saml:AttributeValue></saml:Attribute>
  </saml:AttributeStatement>
</saml:Assertion>""".strip()
    response = f"""<samlp:Response xmlns:samlp="{NS['samlp']}" xmlns:saml="{NS['saml']}"
    ID="{response_id}" Version="2.0" IssueInstant="{_iso(now)}" Destination="{destination}"{irt_attr}>
  <saml:Issuer>{idp_entity_id}</saml:Issuer>
  <samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>
  {assertion}
  {extra_assertion_xml}
</samlp:Response>""".strip()
    return response, assertion_id


def sign_assertion(response_xml: str, assertion_id: str, key_pem: str, cert_pem: str) -> str:
    """Sign the Assertion in place (enveloped signature as its direct child), return the full
    Response XML with the signature inserted. If `assertion_id` doesn't match any element's
    ID (e.g. caller wants an UNSIGNED response), the caller should skip this step entirely."""
    root = etree.fromstring(response_xml.encode())
    assertion_el = root.find(f".//*[@ID='{assertion_id}']")
    signed = XMLSigner(signature_algorithm="rsa-sha256", digest_algorithm="sha256").sign(
        assertion_el, key=key_pem, cert=cert_pem, reference_uri=f"#{assertion_id}", id_attribute="ID"
    )
    # replace the original (unsigned) assertion with the signed one in the parent Response
    parent = assertion_el.getparent()
    parent.replace(assertion_el, signed)
    return etree.tostring(root).decode()


def b64(xml: str) -> str:
    return base64.b64encode(xml.encode()).decode()


def extract_authn_request_id(saml_request_deflated_b64: str) -> str:
    """Inflate the HTTP-Redirect-binding AuthnRequest (raw deflate, as the app sends it) and
    pull out its ID attribute."""
    import re
    import zlib

    xml = zlib.decompressobj(wbits=-15).decompress(base64.b64decode(saml_request_deflated_b64))
    m = re.search(rb'ID="([^"]+)"', xml)
    if not m:
        raise ValueError("no ID found in AuthnRequest")
    return m.group(1).decode()
