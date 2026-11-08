"""SAML 2.0 SP adapter (PLATFORM_SAAS_PLAN §4.2 step 2): signature, audience, time window,
recipient, InResponseTo, and the classic attacks (unsigned, wrong key, tampering, wrapping, XXE)."""

import base64
import urllib.parse
import zlib
from datetime import UTC, datetime, timedelta

import pytest
from lxml import etree

from app.services import saml
from tests.sso_fake_idp import (
    IDP_ENTITY_ID,
    IDP_SSO_URL,
    attacker_keys,
    b64,
    idp_keys,
    saml_response_xml,
    sign_assertion,
    sign_response,
)

SP = "https://api.builder.test/sso/metadata/acme"
ACS = "https://api.builder.test/sso/saml/acme/acs"
REQ = "_req0123456789abcdef"


def _validate(xml: str, **overrides: object) -> saml.SamlIdentity:
    kwargs: dict[str, object] = {
        "idp_cert_pem": idp_keys().cert_pem,
        "idp_entity_id": IDP_ENTITY_ID,
        "sp_entity_id": SP,
        "acs_url": ACS,
    }
    kwargs.update(overrides)
    return saml.validate_response(b64(xml), **kwargs)  # type: ignore[arg-type]


def _response(**kw: object) -> str:
    args: dict[str, object] = {
        "email": "alice@acme.test",
        "sp_entity_id": SP,
        "acs_url": ACS,
        "in_response_to": REQ,
    }
    args.update(kw)
    return saml_response_xml(**args)  # type: ignore[arg-type]


def _reason(xml: str, **overrides: object) -> str:
    with pytest.raises(saml.SamlError) as err:
        _validate(xml, **overrides)
    return err.value.reason


# -- happy paths ------------------------------------------------------------------------------


def test_signed_assertion_is_accepted() -> None:
    ident = _validate(sign_assertion(_response()))
    assert ident.email == "alice@acme.test"
    assert ident.in_response_to == REQ
    assert ident.name == "Alice Smith"


def test_signed_response_is_accepted() -> None:
    assert _validate(sign_response(_response())).email == "alice@acme.test"


def test_email_from_attribute_when_name_id_is_opaque() -> None:
    ident = _validate(sign_assertion(_response(name_id_in_attribute=True, email="Bob@Acme.test")))
    assert ident.email == "bob@acme.test"


def test_bare_base64_certificate_is_accepted() -> None:
    pem = idp_keys().cert_pem
    bare = "".join(line for line in pem.splitlines() if "CERTIFICATE" not in line)
    assert saml.normalize_cert(bare) == saml.normalize_cert(pem)
    assert _validate(sign_assertion(_response()), idp_cert_pem=saml.normalize_cert(bare))


# -- signature attacks ------------------------------------------------------------------------


def test_unsigned_response_is_refused() -> None:
    assert _reason(_response()) == "unsigned"


def test_signed_by_another_key_is_refused() -> None:
    assert _reason(sign_assertion(_response(), attacker_keys())) == "bad_signature"


def test_tampered_after_signing_is_refused() -> None:
    signed = sign_assertion(_response())
    tampered = signed.replace("alice@acme.test", "mallory@acme.test")
    assert _reason(tampered) == "bad_signature"


def test_signature_wrapping_is_refused() -> None:
    """An attacker keeps a genuinely signed assertion and adds their own unsigned one."""
    genuine = etree.fromstring(sign_assertion(_response()).encode())
    evil = etree.fromstring(_response(email="mallory@acme.test").encode())
    evil_assertion = evil.find("{urn:oasis:names:tc:SAML:2.0:assertion}Assertion")
    assert evil_assertion is not None
    genuine.insert(2, evil_assertion)  # before the signed one
    reason = _reason(etree.tostring(genuine).decode())
    assert reason in ("multiple_assertions", "bad_signature", "unsigned")


def test_doctype_and_entities_are_refused() -> None:
    xxe = '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>' + (
        sign_assertion(_response()).replace("alice@acme.test", "&x;")
    )
    assert _reason(xxe) == "malformed"


def test_encrypted_assertion_is_refused_clearly() -> None:
    xml = (
        _response()
        .replace("<saml:Assertion ", "<saml:EncryptedAssertion ")
        .replace("</saml:Assertion>", "</saml:EncryptedAssertion>")
    )
    assert _reason(xml) == "encrypted_assertion_unsupported"


def test_garbage_is_malformed() -> None:
    with pytest.raises(saml.SamlError) as err:
        saml.validate_response(
            "not base64 !!!",
            idp_cert_pem=idp_keys().cert_pem,
            idp_entity_id=IDP_ENTITY_ID,
            sp_entity_id=SP,
            acs_url=ACS,
        )
    assert err.value.reason == "malformed"


# -- assertion checks -------------------------------------------------------------------------


def test_wrong_issuer_is_refused() -> None:
    assert _reason(sign_assertion(_response(issuer="https://evil.test"))) == "wrong_issuer"


def test_wrong_audience_is_refused() -> None:
    xml = sign_assertion(_response(audience="https://other-sp.test"))
    assert _reason(xml) == "wrong_audience"


def test_wrong_recipient_is_refused() -> None:
    xml = sign_assertion(_response(recipient="https://api.builder.test/sso/saml/other/acs"))
    assert _reason(xml) == "wrong_recipient"


def test_expired_assertion_is_refused() -> None:
    past = datetime.now(UTC) - timedelta(hours=1)
    assert _reason(sign_assertion(_response(now=past))) == "expired"


def test_not_yet_valid_assertion_is_refused() -> None:
    future = datetime.now(UTC) + timedelta(hours=1)
    assert _reason(sign_assertion(_response(not_before=future))) == "not_yet_valid"


def test_failed_status_is_refused() -> None:
    xml = sign_response(_response(status="urn:oasis:names:tc:SAML:2.0:status:Requester"))
    assert _reason(xml) == "idp_status"


# -- SP side ---------------------------------------------------------------------------------


def test_authn_request_redirect() -> None:
    url = saml.authn_request_url(
        sp_entity_id=SP, acs_url=ACS, idp_sso_url=IDP_SSO_URL, request_id=REQ
    )
    parsed = urllib.parse.urlparse(url)
    assert url.startswith(IDP_SSO_URL + "?")
    query = urllib.parse.parse_qs(parsed.query)
    xml = zlib.decompress(base64.b64decode(query["SAMLRequest"][0]), -15)
    root = etree.fromstring(xml)
    assert root.get("ID") == REQ
    assert root.get("AssertionConsumerServiceURL") == ACS
    assert root.get("Destination") == IDP_SSO_URL
    issuer = root.find("{urn:oasis:names:tc:SAML:2.0:assertion}Issuer")
    assert issuer is not None and issuer.text == SP


def test_authn_request_keeps_existing_query() -> None:
    url = saml.authn_request_url(
        sp_entity_id=SP, acs_url=ACS, idp_sso_url=IDP_SSO_URL + "?tenant=1", request_id=REQ
    )
    assert url.startswith(IDP_SSO_URL + "?tenant=1&SAMLRequest=")


def test_sp_metadata() -> None:
    root = etree.fromstring(saml.sp_metadata(sp_entity_id=SP, acs_url=ACS).encode())
    assert root.get("entityID") == SP
    ns = {"md": "urn:oasis:names:tc:SAML:2.0:metadata"}
    acs = root.find("md:SPSSODescriptor/md:AssertionConsumerService", ns)
    assert acs is not None and acs.get("Location") == ACS
    assert acs.get("Binding") == "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"


def test_new_request_ids_are_valid_xml_ids_and_unique() -> None:
    ids = {saml.new_request_id() for _ in range(50)}
    assert len(ids) == 50
    assert all(i[0] == "_" and len(i) <= 64 for i in ids)


def test_invalid_certificate_is_refused() -> None:
    with pytest.raises(saml.SamlError) as err:
        saml.normalize_cert("-----BEGIN CERTIFICATE-----\nnope\n-----END CERTIFICATE-----")
    assert err.value.reason == "invalid_certificate"


def test_certificate_summary() -> None:
    summary = saml.cert_summary(idp_keys().cert_pem)
    assert len(summary["sha256_fingerprint"]) == 95  # 32 bytes as AA:BB:...
    assert summary["not_after"]
