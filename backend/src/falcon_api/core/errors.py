"""Framework-independent application error contracts."""

import re

ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


class ApplicationError(Exception):
    """Represent an expected failure that is safe to expose to API clients."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
    ) -> None:
        if ERROR_CODE_PATTERN.fullmatch(code) is None:
            raise ValueError("Application error codes must be stable snake_case values.")
        if not 400 <= status_code <= 599:
            raise ValueError("Application error status codes must be between 400 and 599.")

        super().__init__(message)
        self.code = code
        self.public_message = message
        self.status_code = status_code
