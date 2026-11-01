"""Contract checks for the custom hooks (generated from the spec): the models, the fixed stub
signature and the registry wiring. Your own tests for a hook belong in tests/custom/."""

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.hooks_gen import contracts, registry

ROOT = Path(__file__).resolve().parents[2]


class Test_match_invoice:
    INPUT = {'invoice_no': 'sample', 'amount': '1.50', 'po_amount': '1.50'}
    OUTPUT = {'allowed': True, 'reason': 'sample'}

    def test_the_models_accept_a_valid_sample(self) -> None:
        assert contracts.MatchInput.model_validate(self.INPUT)
        assert contracts.MatchResult.model_validate(self.OUTPUT)

    def test_the_input_model_rejects_wrong_types(self) -> None:
        with pytest.raises(ValidationError):
            contracts.MatchInput.model_validate({**self.INPUT, "invoice_no": []})
        with pytest.raises(ValidationError):
            contracts.MatchInput.model_validate({**self.INPUT, "amount": []})
        with pytest.raises(ValidationError):
            contracts.MatchInput.model_validate({**self.INPUT, "po_amount": []})

    def test_the_models_reject_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            contracts.MatchInput.model_validate({**self.INPUT, "unknown_field": 1})
        with pytest.raises(ValidationError):
            contracts.MatchResult.model_validate({**self.OUTPUT, "unknown_field": 1})

    def test_the_input_model_needs_its_required_fields(self) -> None:
        with pytest.raises(ValidationError):
            contracts.MatchInput.model_validate(
                {k: v for k, v in self.INPUT.items() if k != "invoice_no"}
            )
        with pytest.raises(ValidationError):
            contracts.MatchInput.model_validate(
                {k: v for k, v in self.INPUT.items() if k != "amount"}
            )
        with pytest.raises(ValidationError):
            contracts.MatchInput.model_validate(
                {k: v for k, v in self.INPUT.items() if k != "po_amount"}
            )

    def test_the_stub_signature_is_unchanged(self) -> None:
        text = (ROOT / "app/custom/hooks/match_invoice.py").read_text(encoding="utf-8")
        lines = text.splitlines()
        assert lines.count('def match_invoice(data: MatchInput) -> MatchResult:  # platform:signature (fixed)') == 1
        assert lines.count('    # <agent:body hook=match_invoice>') == 1
        assert lines.count("    # </agent:body>") == 1
        function = next(
            n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == "match_invoice"
        )
        assert [a.arg for a in function.args.args] == ["data"]
        assert ast.unparse(function.args.args[0].annotation) == "MatchInput"
        assert ast.unparse(function.returns) == "MatchResult"

    def test_the_function_is_wired_into_the_registry(self) -> None:
        hook = registry.HOOKS["match_invoice"]
        assert hook["fn"].__name__ == "match_invoice"
        assert hook["input"] is contracts.MatchInput
        assert hook["output"] is contracts.MatchResult
