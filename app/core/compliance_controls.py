"""Control catalogue for SOC 2, HIPAA and PCI DSS (D47), derived purely from a Spec.

Each control reads facts from the spec (never from a running system): `check(spec)` answers met /
unmet / not_applicable with a reason, `evidence(spec)` lists the spec facts behind the answer, and
`tests` names the tests that prove the behaviour (in the GENERATED project, or in the platform repo).
Evidence holds names, counts and settings only: never a secret, a key, a protected value or a row.
This is a mapping aid for an auditor, not a certification."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from app.core.spec_models import Spec
from app.core.validation_compliance import is_direct_identifier

Status = Literal["met", "unmet", "not_applicable"]
FRAMEWORKS = ("soc2", "hipaa", "pci")
GENERATED = "generated"
PLATFORM = "platform"


@dataclass(frozen=True)
class TestRef:
    __test__ = False  # not a pytest class
    file: str
    name: str
    where: str = GENERATED

    def as_dict(self) -> dict[str, str]:
        return {"file": self.file, "name": self.name, "where": self.where}


@dataclass(frozen=True)
class Control:
    id: str
    framework: str
    title: str
    description: str
    applies: Callable[[Spec], bool]
    check: Callable[[Spec], tuple[Status, str]]
    evidence: Callable[[Spec], list[dict[str, Any]]]
    tests: tuple[TestRef, ...]


def _g(file: str, *names: str) -> tuple[TestRef, ...]:
    return tuple(TestRef(f"tests/{file}", n) for n in names)


def _p(file: str, *names: str) -> tuple[TestRef, ...]:
    return tuple(TestRef(file, n, PLATFORM) for n in names)


# -- spec facts ---------------------------------------------------------------------------------

def _reg_on(s: Spec) -> bool:
    return s.regulated is not None and s.regulated.enabled


def _comp_on(s: Spec) -> bool:
    return s.compliance is not None and s.compliance.enabled


def _auth_on(s: Spec) -> bool:
    return s.auth is not None and s.auth.enabled


def _role_names(s: Spec) -> list[str]:
    return sorted(r.name for r in s.auth.roles) if s.auth is not None else []


def _fields(s: Spec) -> list[dict[str, Any]]:
    if s.regulated is None:
        return []
    return [{"entity": f.entity, "field": f.field, "mode": f.mode, "searchable": f.searchable}
            for f in s.regulated.fields]


def _always(_: Spec) -> bool:
    return True


def _f(path: str, value: Any) -> dict[str, Any]:
    return {"fact": path, "value": value}


def _ok(cond: bool, met: str, unmet: str) -> tuple[Status, str]:
    return ("met", met) if cond else ("unmet", unmet)


# -- checks, one per theme (reused by the three frameworks) ---------------------------------------

def _access(s: Spec) -> tuple[Status, str]:
    if not _auth_on(s):
        return "unmet", "auth is not enabled: every route is open"
    return _ok(bool(s.auth and s.auth.permissions), "auth is enabled and permissions map roles to operations",
               "auth is enabled but no permission grants any role an operation")


def _access_ev(s: Spec) -> list[dict[str, Any]]:
    a = s.auth
    return [_f("auth.enabled", _auth_on(s)), _f("auth.roles", _role_names(s)),
            _f("auth.permissions.count", len(a.permissions) if a else 0),
            _f("authorization.model", s.authorization.model if s.authorization else "rbac")]


def _identity(s: Spec) -> tuple[Status, str]:
    return _ok(_auth_on(s), "every request is made by an authenticated, individually identified user",
               "auth is not enabled: callers are anonymous")


def _identity_ev(s: Spec) -> list[dict[str, Any]]:
    a = s.auth
    return [_f("auth.enabled", _auth_on(s)), _f("auth.provider", a.provider if a else None),
            _f("auth.access_token_ttl_minutes", a.access_token_ttl_minutes if a else None)]


def _encryption(s: Spec) -> tuple[Status, str]:
    if not _reg_on(s):
        return "unmet", "regulated mode is off: no field is encrypted at rest"
    return _ok(bool(s.regulated and s.regulated.fields), "regulated mode protects the listed fields at rest",
               "regulated mode is on but lists no protected field")


def _encryption_ev(s: Spec) -> list[dict[str, Any]]:
    return [_f("regulated.enabled", _reg_on(s)), _f("regulated.fields", _fields(s))]


def _keys(s: Spec) -> tuple[Status, str]:
    if not _reg_on(s):
        return "unmet", "regulated mode is off: no key custody is defined"
    kp = s.regulated.key_provider if s.regulated else "env"
    return _ok(kp in ("file", "command"), f"keys are customer-managed (key_provider {kp}) and rotatable",
               "the key comes from the environment, which is not customer-managed")


def _keys_ev(s: Spec) -> list[dict[str, Any]]:
    return [_f("regulated.enabled", _reg_on(s)), _f("regulated.key_provider", s.regulated.key_provider if s.regulated else None)]


def _audit(s: Spec) -> tuple[Status, str]:
    parts = []
    if s.history:
        parts.append(f"change history on {len(s.history)} entities")
    if s.events is not None and s.events.enabled:
        parts.append("event outbox")
    if _comp_on(s) and s.compliance and s.compliance.break_glass.enabled:
        parts.append("audited break-glass reads")
    return (("met", "audit trail: " + ", ".join(parts)) if parts
            else ("unmet", "no change history, event outbox or audited access is configured"))


def _audit_ev(s: Spec) -> list[dict[str, Any]]:
    return [_f("history.entities", sorted(h.entity for h in s.history)),
            _f("events.enabled", bool(s.events and s.events.enabled)),
            _f("compliance.break_glass.enabled", bool(s.compliance and s.compliance.break_glass.enabled))]


def _retention(s: Spec) -> tuple[Status, str]:
    c = s.compliance
    if not _comp_on(s) or c is None:
        return "unmet", "the compliance block is off: no retention rule or legal hold"
    return _ok(bool(c.retention), "retention rules purge or anonymise old rows and respect legal holds",
               "compliance is on but no retention rule is defined")


def _retention_ev(s: Spec) -> list[dict[str, Any]]:
    c = s.compliance
    return [_f("compliance.enabled", _comp_on(s)),
            _f("compliance.retention", [{"entity": r.entity, "days": r.days, "action": r.action}
                                         for r in (c.retention if c else [])])]


def _handles_personal(s: Spec) -> bool:
    return bool(s.regulated and s.regulated.fields) or _comp_on(s)


def _consent(s: Spec) -> tuple[Status, str]:
    c = s.compliance
    if not _handles_personal(s):
        return "not_applicable", "no protected field and no compliance block: no personal data is declared"
    if not _comp_on(s) or c is None:
        return "unmet", "personal data is declared but the compliance block (consent) is off"
    if not c.consent_purposes:
        return "unmet", "no consent purpose is configured"
    if c.export_consent_purpose is None:
        return "unmet", "consent purposes are configured but nothing in the spec consults them (no export_consent_purpose)"
    return "met", f"consent purposes are configured and the export is gated on {c.export_consent_purpose!r}"


def _consent_ev(s: Spec) -> list[dict[str, Any]]:
    c = s.compliance
    return [_f("compliance.enabled", _comp_on(s)), _f("compliance.consent_purposes", sorted(c.consent_purposes) if c else [])]


def _break_glass(s: Spec) -> tuple[Status, str]:
    c = s.compliance
    if not _reg_on(s):
        return "not_applicable", "regulated mode is off: no protected data to reach in an emergency"
    if not _comp_on(s) or c is None or not c.break_glass.enabled:
        return "unmet", "no break-glass procedure is configured for emergency access"
    return _ok(bool(c.break_glass.roles), f"emergency access is time-boxed to {c.break_glass.max_minutes} minutes and audited",
               "break-glass is on but no role may use it")


def _break_glass_ev(s: Spec) -> list[dict[str, Any]]:
    bg = s.compliance.break_glass if s.compliance else None
    return [_f("compliance.break_glass.enabled", bool(bg and bg.enabled)),
            _f("compliance.break_glass.roles", sorted(bg.roles) if bg else []),
            _f("compliance.break_glass.max_minutes", bg.max_minutes if bg else None)]


def _field_types(s: Spec) -> dict[tuple[str, str], str]:
    return {(e.name, f.name): f.type for e in s.entities for f in e.fields}


def _kept_identifiers(s: Spec) -> list[str]:
    c = s.compliance
    types = _field_types(s)
    return sorted(f"{x.entity}.{x.field}" for x in (c.export_fields if c else [])
                  if x.treatment == "keep" and is_direct_identifier(x.field, types.get((x.entity, x.field))))


def _export(s: Spec) -> tuple[Status, str]:
    c = s.compliance
    if not _handles_personal(s):
        return "not_applicable", "no personal data is declared"
    if not _comp_on(s) or c is None or not c.export_entities:
        return "unmet", "no de-identified export is configured"
    if not c.export_fields:
        return "unmet", "an export entity is configured without any field treatment"
    kept = _kept_identifiers(s)
    if kept:
        return "unmet", f"export keeps direct identifier(s): {', '.join(kept)}"
    return "met", "no kept export field is a direct identifier (same heuristic validation enforces); unlisted fields are dropped"


def _export_ev(s: Spec) -> list[dict[str, Any]]:
    c = s.compliance
    return [_f("compliance.export_entities", sorted(e.entity for e in c.export_entities) if c else []),
            _f("compliance.export_fields", [{"entity": x.entity, "field": x.field, "treatment": x.treatment}
                                             for x in (c.export_fields if c else [])]),
            _f("compliance.export_consent_purpose", c.export_consent_purpose if c else None),
            _f("compliance.export_kept_identifiers", _kept_identifiers(s))]


def _secrets(s: Spec) -> tuple[Status, str]:
    obs = s.observability
    if obs is not None and obs.enabled:
        return "met", "observability is enabled: its redaction of secret keys is built in (plus extra_redact_keys)"
    if _reg_on(s) and s.regulated and s.regulated.fields:
        return "met", "regulated mode is on with protected fields: they are masked in logs and spans"
    return "unmet", "neither observability redaction nor regulated masking is configured"


def _secrets_ev(s: Spec) -> list[dict[str, Any]]:
    obs = s.observability
    return [_f("observability.enabled", bool(obs and obs.enabled)),
            _f("observability.extra_redact_keys", sorted(obs.extra_redact_keys) if obs else []),
            _f("regulated.protected_field_count", len(s.regulated.fields) if s.regulated else 0)]


def _tenancy(s: Spec) -> tuple[Status, str]:
    if not _auth_on(s):
        return "unmet", "auth is not enabled"
    if s.auth is not None and s.auth.multi_tenant:
        return "met", "rows are scoped to a tenant and cross-tenant references are refused"
    return "not_applicable", "the project is single-tenant"


def _tenancy_ev(s: Spec) -> list[dict[str, Any]]:
    return [_f("auth.multi_tenant", bool(s.auth and s.auth.multi_tenant))]


def _headers(s: Spec) -> tuple[Status, str]:
    return _ok(bool(s.auth and s.auth.security_headers_enabled), "security headers are sent on every response",
               "security headers are disabled or auth is off")


def _headers_ev(s: Spec) -> list[dict[str, Any]]:
    return [_f("auth.security_headers_enabled", bool(s.auth and s.auth.security_headers_enabled))]


def _monitor(s: Spec) -> tuple[Status, str]:
    obs = s.observability
    return _ok(bool(obs and obs.enabled), "traces and metrics are exported; denied requests are counted",
               "observability is not enabled")


def _monitor_ev(s: Spec) -> list[dict[str, Any]]:
    obs = s.observability
    return [_f("observability.enabled", bool(obs and obs.enabled)), _f("observability.metrics", bool(obs and obs.metrics))]


def _integrity(s: Spec) -> tuple[Status, str]:
    enc = [f for f in (s.regulated.fields if s.regulated else []) if f.mode == "encrypt"]
    if not _reg_on(s):
        return "unmet", "regulated mode is off: stored values are not authenticated"
    return _ok(bool(enc), "encrypted values are authenticated and bound to their column: tampering is refused",
               "no field uses authenticated encryption")


def _mask(s: Spec) -> tuple[Status, str]:
    if not _reg_on(s):
        return "unmet", "regulated mode is off: nothing is masked"
    if not (s.regulated and s.regulated.fields):
        return "unmet", "no field is protected"
    return "met", "regulated mode is on: the generated project masks the listed protected fields"


def _pan(s: Spec) -> tuple[Status, str]:
    if not (s.regulated and s.regulated.fields) and s.payments is None:
        return "not_applicable", "no protected field and no payments: no account data is stored"
    return _encryption(s)


def _pan_ev(s: Spec) -> list[dict[str, Any]]:
    return _encryption_ev(s) + [_f("payments.configured", s.payments is not None)]


# test references (names verified by tests/unit/test_compliance_controls.py)
T_ENC = _g("test_regulated.py", "test_encrypt_decrypt_round_trip_hides_the_plaintext",
           "test_the_same_value_encrypts_differently_each_time", "test_a_tokenised_column_refuses_plaintext")
T_KEYS = _g("test_regulated.py", "test_rotation_keeps_old_rows_readable_and_a_removed_key_fails_closed",
            "test_a_key_file_open_to_others_is_refused", "test_error_messages_never_carry_key_material")
T_INTEGRITY = _g("test_regulated.py", "test_a_tampered_ciphertext_is_refused",
                 "test_a_ciphertext_moved_to_another_column_does_not_decrypt")
T_MASK = _g("test_regulated.py", "test_mask_replaces_protected_values_only")
T_ACCESS = (_g("test_access.py", "test_customers_routes_need_a_signed_in_user")
            + _p("tests/api/test_access_matrix.py", "test_role_matrix_on_a_shared_project"))
T_IDENT = (_g("test_access.py", "test_customers_routes_need_a_signed_in_user")
           + _p("tests/api/test_access_matrix.py", "test_unauthenticated_sweep_is_401_everywhere"))
T_TENANT = _g("test_tenancy.py", "test_customers_rows_stay_inside_their_tenant",
              "test_the_first_user_creates_a_tenant_and_becomes_its_admin")
T_AUDIT = (_g("test_change_history.py", "test_create_records_each_listed_field_with_the_actor",
              "test_update_records_only_changed_listed_fields_and_never_others")
           + _p("tests/api/test_access_matrix.py", "test_denied_attempts_are_audited"))
T_RETAIN = _g("test_compliance.py", "test_retention_purges_expired_rows", "test_purge_refuses_rows_under_legal_hold",
              "test_legal_hold_release_allows_purge")
T_CONSENT = _g("test_compliance.py", "test_consent_grant_and_withdraw")
T_BG = _g("test_compliance.py", "test_break_glass_is_audited_and_time_boxed",
          "test_break_glass_denied_without_role_or_after_expiry")
T_EXPORT = _g("test_compliance.py", "test_export_has_no_direct_identifiers", "test_export_skips_subjects_without_consent")
T_SECRETS = (_g("test_observability.py", "test_secrets_never_reach_an_exported_span",
                "test_extra_redact_keys_from_the_spec_are_honoured")
             + _p("tests/unit/test_generated_zip_secret_scan.py", "test_a_generated_zip_holds_no_credential"))
T_MONITOR = _g("test_observability.py", "test_a_request_becomes_a_server_span_named_after_the_route",
               "test_denied_events_are_counted")
T_HEADERS = _p("tests/unit/test_regulated_spec.py", "test_compose_wires_the_key_file_and_silences_the_access_log")
T_EVENTS = _g("test_events.py", "test_a_create_writes_its_event_in_the_same_transaction")


def _c(cid: str, fw: str, title: str, desc: str, applies: Callable[[Spec], bool],
       check: Callable[[Spec], tuple[Status, str]], ev: Callable[[Spec], list[dict[str, Any]]],
       tests: tuple[TestRef, ...]) -> Control:
    return Control(cid, fw, title, desc, applies, check, ev, tests)


CONTROLS: tuple[Control, ...] = (
    _c("SOC2-CC6.1", "soc2", "Logical access controls", "Access to data is limited to authenticated users by role.",
       _always, _access, _access_ev, T_ACCESS),
    _c("SOC2-CC6.2", "soc2", "User identification", "Users are individually identified before access is granted.",
       _always, _identity, _identity_ev, T_IDENT),
    _c("SOC2-CC6.3", "soc2", "Tenant isolation", "One customer's data is not reachable by another.",
       _always, _tenancy, _tenancy_ev, T_TENANT),
    _c("SOC2-CC6.6", "soc2", "Boundary protection", "Responses carry browser security headers and the access log is quiet.",
       _always, _headers, _headers_ev, T_HEADERS),
    _c("SOC2-CC6.7", "soc2", "Encryption of data at rest", "Sensitive fields are encrypted or tokenised before storage.",
       _always, _encryption, _encryption_ev, T_ENC),
    _c("SOC2-CC6.1-KEY", "soc2", "Cryptographic key custody", "Keys are customer-managed, rotatable and never in the spec.",
       _always, _keys, _keys_ev, T_KEYS),
    _c("SOC2-CC7.2", "soc2", "Security monitoring", "System activity is traced and denied requests are counted.",
       _always, _monitor, _monitor_ev, T_MONITOR),
    _c("SOC2-CC7.3", "soc2", "Audit trail", "Changes are recorded with who made them.",
       _always, _audit, _audit_ev, T_AUDIT),
    _c("SOC2-CC6.5", "soc2", "Retention and disposal", "Data is removed after its retention period unless on legal hold.",
       _always, _retention, _retention_ev, T_RETAIN),
    _c("SOC2-P2.1", "soc2", "Consent", "Consent to a purpose is recorded and can be withdrawn.",
       _always, _consent, _consent_ev, T_CONSENT),
    _c("SOC2-CC6.8", "soc2", "Secret hygiene", "Secrets never reach spans, logs or the spec.",
       _always, _secrets, _secrets_ev, T_SECRETS),
    _c("HIPAA-164.312(a)(1)", "hipaa", "Access control", "Technical policies limit access to authorised persons.",
       _always, _access, _access_ev, T_ACCESS),
    _c("HIPAA-164.312(a)(2)(i)", "hipaa", "Unique user identification", "Each user has a unique identity.",
       _always, _identity, _identity_ev, T_IDENT),
    _c("HIPAA-164.312(a)(2)(ii)", "hipaa", "Emergency access procedure", "A documented, audited way to reach data in an emergency.",
       _always, _break_glass, _break_glass_ev, T_BG),
    _c("HIPAA-164.312(a)(2)(iv)", "hipaa", "Encryption and decryption", "ePHI fields are encrypted at rest.",
       _always, _encryption, _encryption_ev, T_ENC),
    _c("HIPAA-164.312(b)", "hipaa", "Audit controls", "Activity on systems holding ePHI is recorded.",
       _always, _audit, _audit_ev, T_AUDIT),
    _c("HIPAA-164.312(c)(1)", "hipaa", "Integrity", "ePHI is not altered or destroyed improperly.",
       _always, _integrity, _encryption_ev, T_INTEGRITY),
    _c("HIPAA-164.312(d)", "hipaa", "Person or entity authentication", "Users prove who they are.",
       _always, _identity, _identity_ev, T_IDENT),
    _c("HIPAA-164.514(b)", "hipaa", "De-identified export", "Exports keep no direct identifier (spec heuristic) and can be gated on consent.",
       _always, _export, _export_ev, T_EXPORT),
    _c("PCI-3.2", "pci", "Limit data retention", "Stored data is kept no longer than needed.",
       _always, _retention, _retention_ev, T_RETAIN),
    _c("PCI-3.4", "pci", "Mask displayed account data", "Protected values are masked when displayed or logged.",
       _always, _mask, _encryption_ev, T_MASK),
    _c("PCI-3.5", "pci", "Protect stored account data", "Stored account data is unreadable (encrypted or tokenised).",
       _always, _pan, _pan_ev, T_ENC),
    _c("PCI-3.6", "pci", "Key management", "Cryptographic keys are protected and managed by the customer.",
       _always, _keys, _keys_ev, T_KEYS),
    _c("PCI-7.2", "pci", "Access by need to know", "Access is granted per role and operation.",
       _always, _access, _access_ev, T_ACCESS),
    _c("PCI-8.2", "pci", "Unique user IDs", "All users have a unique ID before access.",
       _always, _identity, _identity_ev, T_IDENT),
    _c("PCI-10.2", "pci", "Audit logs", "Audit logs record user actions on system components.",
       _always, _audit, _audit_ev, T_AUDIT + T_EVENTS),
)


def evaluate(control: Control, spec: Spec) -> dict[str, Any]:
    status, reason = control.check(spec) if control.applies(spec) else ("not_applicable", "not applicable to this spec")
    return {
        "id": control.id,
        "framework": control.framework,
        "title": control.title,
        "description": control.description,
        "status": status,
        "reason": reason,
        "evidence": control.evidence(spec),
        "tests": [t.as_dict() for t in control.tests],
    }
