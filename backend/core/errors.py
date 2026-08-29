from __future__ import annotations


class ApplicationError(Exception):
    """Base class for errors raised by application services."""

    def __init__(self, detail: str, status_code: int) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class NotFoundError(ApplicationError):
    """A requested application resource does not exist."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail, 404)


class ConflictError(ApplicationError):
    """A requested state transition conflicts with existing data."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail, 409)


class ValidationError(ApplicationError):
    """A service-level validation rule rejected the request."""

    def __init__(self, detail: str, status_code: int = 400) -> None:
        super().__init__(detail, status_code)


class IntegrationError(ApplicationError):
    """An external integration could not complete a service request."""

    def __init__(self, detail: str, status_code: int = 502) -> None:
        super().__init__(detail, status_code)
