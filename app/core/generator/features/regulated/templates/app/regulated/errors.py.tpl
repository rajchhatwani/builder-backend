"""Errors of regulated mode (generated). Messages never carry key material or a protected value."""


class RegulatedError(RuntimeError):
    """A key, ciphertext or configuration problem. Callers treat it as a refusal: nothing partial is returned."""
