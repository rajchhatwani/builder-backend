"""B3-9: name/version validation and check_requirements against hostile input."""

import pytest

from app.services.dependency_policy_service import (
    check_requirements,
    normalize_name,
    parse_requirement,
    validate_version,
    verify_install_plan,
)

H = "sha256:" + "a" * 64


def test_name_normalisation_pep503() -> None:
    assert normalize_name("Python_Dateutil") == "python-dateutil"
    assert normalize_name("a..b__c--d") == "a-b-c-d"


@pytest.mark.parametrize(
    "name",
    ["", "-x", "x-", "git+https://x/y", "a/b", "a b", "a[extra]", "a@1", "../x", "pаndas", "ｐandas", "a;b", "x" * 101],
)
def test_bad_names(name: str) -> None:
    with pytest.raises(ValueError):
        normalize_name(name)


@pytest.mark.parametrize(
    "v", ["", "1", "1.0.*", ">=1", "1.0+local", "1!2.0", "01.2", "1.2.3.4.5", "latest", "1.0 ", "١.٠", "1.0;x"]
)
def test_bad_versions(v: str) -> None:
    if v == "1":
        assert validate_version(v) == "1"
        return
    with pytest.raises(ValueError):
        validate_version(v)


def test_good_versions() -> None:
    for v in ("1.2.3", "2.0.0rc1", "1.0.post2", "3.1.dev4", "0.1"):
        assert validate_version(v) == v


def test_parse_with_hashes() -> None:
    assert parse_requirement(f"Orjson == 3.10.0 --hash={H}") == ("orjson", "3.10.0", [H])
    with pytest.raises(ValueError):
        parse_requirement("orjson==3.10.0 --hash=md5:abc")


def test_curated_and_allow_list_pass() -> None:
    v = check_requirements("fastapi==0.115.6\n# c\n\nOrjson==3.10.0\n")
    assert v.ok and [r.source for r in v.results] == ["curated:web-core", "allow_list"]


def test_curated_wrong_pin_is_blocked_as_unknown() -> None:
    v = check_requirements(["fastapi==0.1.0"])
    assert not v.ok and "unknown" in (v.results[0].reason or "")


def test_unknown_blocked_until_approved() -> None:
    assert not check_requirements("leftpad==1.0.0").ok
    line = f"leftpad==1.0.0 --hash={H}"
    assert check_requirements(line, [("leftpad", "1.0.0", [H])]).ok
    # an approval of another version does not carry over
    assert not check_requirements(f"leftpad==1.0.1 --hash={H}", [("leftpad", "1.0.0", [H])]).ok


def test_approved_pin_requires_matching_hashes() -> None:
    other = "sha256:" + "c" * 64
    pins = [("leftpad", "1.0.0", [H])]
    assert not check_requirements("leftpad==1.0.0", pins).ok  # no hashes on the line
    assert not check_requirements(f"leftpad==1.0.0 --hash={other}", pins).ok
    assert not check_requirements(f"leftpad==1.0.0 --hash={H} --hash={other}", pins).ok
    assert not check_requirements(f"leftpad==1.0.0 --hash={H}", [("leftpad", "1.0.0")]).ok
    assert not check_requirements(f"leftpad==1.0.0 --hash={H}", [("leftpad", "1.0.0", [])]).ok


def test_verify_install_plan_fails_closed() -> None:
    other = "sha256:" + "c" * 64
    pins = [("leftpad", "1.0.0", [H])]
    req = f"leftpad==1.0.0 --hash={H}\norjson==3.10.0 --hash={other}"
    good = {"leftpad": [H], "Orjson": [other]}
    assert verify_install_plan(req, good, pins).ok
    assert not verify_install_plan(req, {**good, "leftpad": [other]}, pins).ok  # swapped artifact
    assert not verify_install_plan(req, {"leftpad": [H]}, pins).ok  # missing orjson
    assert not verify_install_plan(req, {**good, "evil": [H]}, pins).ok  # extra package
    assert not verify_install_plan(req, {**good, "leftpad": []}, pins).ok
    assert not verify_install_plan(req, {**good, "leftpad": ["md5:x"]}, pins).ok
    assert not verify_install_plan(req, good, []).ok  # approval gone (revoked/expired)
    # curated pin without line hashes cannot be verified
    assert not verify_install_plan("fastapi==0.115.6", {"fastapi": [H]}).ok
    assert verify_install_plan(f"fastapi==0.115.6 --hash={H}", {"fastapi": [H]}).ok
    assert not verify_install_plan(f"fastapi==0.115.6 --hash={H}", {"fastapi": [other]}).ok


@pytest.mark.parametrize(
    "line",
    [
        "-r other.txt",
        "--index-url https://evil.example/simple",
        "--extra-index-url=https://evil.example",
        "-e .",
        "git+https://github.com/x/y.git",
        "git+ssh://git@github.com/x/y@main#egg=y",
        "https://evil.example/p-1.0.tar.gz",
        "pkg @ https://evil.example/p.whl",
        "./local/path",
        "/etc/passwd",
        "fastapi[all]==0.115.6",
        "fastapi>=0.115",
        "fastapi~=0.115.6",
        "fastapi==0.115.*",
        "fastapi==0.115.6; python_version>'3'",
        "fastapi",
        "fastapi==0.115.6 --install-option=x",
        "fаstapi==0.115.6",  # cyrillic a
        "orjson==3.10.0‮",
        "orjson==3.10.0\x00",
        "orjson==3.10.0 --hash=sha256:zz",
    ],
)
def test_hostile_lines_blocked(line: str) -> None:
    v = check_requirements([line])
    assert not v.ok and not v.results[0].allowed


def test_one_bad_line_blocks_the_set_and_non_strings_fail_closed() -> None:
    v = check_requirements(["fastapi==0.115.6", "-r x"])
    assert not v.ok and len(v.blocked) == 1
    assert not check_requirements([None, 3]).ok  # type: ignore[list-item]
