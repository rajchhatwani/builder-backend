"""Contract checks for the custom hooks (generated from the spec): the models, the fixed stub
signature and the registry wiring. Your own tests for a hook belong in tests/custom/."""

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.hooks_gen import contracts, registry

ROOT = Path(__file__).resolve().parents[2]


class Test_announce_order:
    INPUT = {'id': '00000000-0000-4000-8000-000000000001', 'reference': 'sample'}
    OUTPUT = {'sent': True}

    def test_the_models_accept_a_valid_sample(self) -> None:
        assert contracts.AnnounceInput.model_validate(self.INPUT)
        assert contracts.AnnounceResult.model_validate(self.OUTPUT)

    def test_the_input_model_rejects_wrong_types(self) -> None:
        with pytest.raises(ValidationError):
            contracts.AnnounceInput.model_validate({**self.INPUT, "id": []})
        with pytest.raises(ValidationError):
            contracts.AnnounceInput.model_validate({**self.INPUT, "reference": []})

    def test_the_models_reject_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            contracts.AnnounceInput.model_validate({**self.INPUT, "unknown_field": 1})
        with pytest.raises(ValidationError):
            contracts.AnnounceResult.model_validate({**self.OUTPUT, "unknown_field": 1})

    def test_the_input_model_needs_its_required_fields(self) -> None:
        with pytest.raises(ValidationError):
            contracts.AnnounceInput.model_validate(
                {k: v for k, v in self.INPUT.items() if k != "id"}
            )
        with pytest.raises(ValidationError):
            contracts.AnnounceInput.model_validate(
                {k: v for k, v in self.INPUT.items() if k != "reference"}
            )

    def test_the_stub_signature_is_unchanged(self) -> None:
        text = (ROOT / "app/custom/hooks/announce_order.py").read_text(encoding="utf-8")
        lines = text.splitlines()
        assert lines.count('def announce_order(data: AnnounceInput) -> AnnounceResult:  # platform:signature (fixed)') == 1
        assert lines.count('    # <agent:body hook=announce_order>') == 1
        assert lines.count("    # </agent:body>") == 1
        function = next(
            n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == "announce_order"
        )
        assert [a.arg for a in function.args.args] == ["data"]
        assert ast.unparse(function.args.args[0].annotation) == "AnnounceInput"
        assert ast.unparse(function.returns) == "AnnounceResult"

    def test_the_function_is_wired_into_the_registry(self) -> None:
        hook = registry.HOOKS["announce_order"]
        assert hook["fn"].__name__ == "announce_order"
        assert hook["input"] is contracts.AnnounceInput
        assert hook["output"] is contracts.AnnounceResult
