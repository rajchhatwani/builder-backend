class AppError(Exception):
    """Domain error that renders as the builder's structured error envelope.

    Framework-free (no FastAPI import) so services/ can raise it without pulling
    in FastAPI; app/errors.py maps it to a JSONResponse.
    """

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: list[dict[str, object]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or []
        self.headers = headers or {}
