class DomainError(Exception):
    def __init__(
        self, code: str, message: str, status_code: int = 400, details: object | None = None,
        *, headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        self.headers = headers
