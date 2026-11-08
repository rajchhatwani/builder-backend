"""Contract checks for the custom hooks (generated from the spec): the models, the fixed stub
signature and the registry wiring. Your own tests for a hook belong in tests/custom/."""

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.hooks_gen import contracts, registry

ROOT = Path(__file__).resolve().parents[2]


class Test_check_request:
    INPUT = {'days': 1, 'reason': 'sample'}
    OUTPUT = {'valid': True, 'message': 'sample'}

    def test_the_models_accept_a_valid_sample(self) -> None:
        assert contracts.RequestInput.model_validate(self.INPUT)
        assert contracts.RequestResult.model_validate(self.OUTPUT)

    def test_the_input_model_rejects_wrong_types(self) -> None:
        with pytest.raises(ValidationError):
            contracts.RequestInput.model_validate({**self.INPUT, "days": []})
        with pytest.raises(ValidationError):
            contracts.RequestInput.model_validate({**self.INPUT, "reason": []})

    def test_the_models_reject_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            contracts.RequestInput.model_validate({**self.INPUT, "unknown_field": 1})
        with pytest.raises(ValidationError):
            contracts.RequestResult.model_validate({**self.OUTPUT, "unknown_field": 1})

    def test_the_input_model_needs_its_required_fields(self) -> None:
        with pytest.raises(ValidationError):
            contracts.RequestInput.model_validate(
                {k: v for k, v in self.INPUT.items() if k != "days"}
            )

    def test_the_stub_signature_is_unchanged(self) -> None:
        text = (ROOT / "app/custom/hooks/check_request.py").read_text(encoding="utf-8")
        lines = text.splitlines()
        assert lines.count('def check_request(data: RequestInput) -> RequestResult:  # platform:signature (fixed)') == 1
        assert lines.count('    # <agent:body hook=check_request>') == 1
        assert lines.count("    # </agent:body>") == 1
        function = next(
            n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == "check_request"
        )
        assert [a.arg for a in function.args.args] == ["data"]
        assert ast.unparse(function.args.args[0].annotation) == "RequestInput"
        assert ast.unparse(function.returns) == "RequestResult"

    def test_the_function_is_wired_into_the_registry(self) -> None:
        hook = registry.HOOKS["check_request"]
        assert hook["fn"].__name__ == "check_request"
        assert hook["input"] is contracts.RequestInput
        assert hook["output"] is contracts.RequestResult
