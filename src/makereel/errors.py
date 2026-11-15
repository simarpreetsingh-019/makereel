"""One error hierarchy for the whole app.

Every expected failure is a `MakereelError` with a short message for people and an optional
hint on how to fix it. The CLI prints them without a traceback; the API turns them into
`{"error": {"code", "message", "hint"}}` with the matching HTTP status.
"""
from __future__ import annotations


class MakereelError(Exception):
    code = "error"
    status = 500

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.message, self.hint = message, hint

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "hint": self.hint}


class ConfigError(MakereelError):
    code, status = "config", 400


class InvalidInput(MakereelError):
    code, status = "invalid_input", 400


class NotFound(MakereelError):
    code, status = "not_found", 404


class Forbidden(MakereelError):
    code, status = "forbidden", 403


class Conflict(MakereelError):
    code, status = "conflict", 409


class SourceError(MakereelError):
    """A link could not be opened or downloaded (private, removed, region-locked, offline...)."""
    code, status = "source", 422


class MediaError(MakereelError):
    """ffmpeg / ffprobe / a model failed on a file."""
    code, status = "media", 500


class DependencyMissing(MakereelError):
    """A required tool (ffmpeg with libass, a JS runtime...) is not installed."""
    code, status = "dependency", 503
