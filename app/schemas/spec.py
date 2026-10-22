from pydantic import BaseModel

from app.core.validation import ValidationIssue


class ValidationReport(BaseModel):
    valid: bool
    issues: list[ValidationIssue]
