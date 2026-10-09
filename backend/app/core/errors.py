class ToolError(Exception):
    """An expected, user-facing failure inside a tool (corrupt file, wrong password...).

    The message is shown verbatim to the user. Anything else raised by a tool is
    treated as an internal error and only logged.
    """


class Cancelled(Exception):
    """Raised inside a running job when the user cancels it."""


class ApiError(Exception):
    """An error that maps directly onto an HTTP response."""

    def __init__(self, status_code: int, code: str, message: str, detail=None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "detail": self.detail}}
