"""A tiny method + path router, so routes read like `@api.get("/jobs/{job_id}")`."""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, unquote

from ..errors import InvalidInput, MakereelError, NotFound


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, str]
    headers: Any
    body: bytes = b""
    params: dict[str, str] = field(default_factory=dict)
    stream: Any = None            # the raw socket file, for large uploads
    length: int = 0

    def json(self) -> dict:
        if not self.body:
            return {}
        try:
            data = json.loads(self.body)
        except ValueError as e:
            raise InvalidInput("request body is not valid JSON") from e
        if not isinstance(data, dict):
            raise InvalidInput("request body must be a JSON object")
        return data


@dataclass
class Response:
    body: Any = None
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)


Handler = Callable[[Request], Any]
_PARAM = re.compile(r"\{(\w+)\}")


class Router:
    def __init__(self, prefix: str = ""):
        self.prefix = prefix.rstrip("/")
        self.routes: list[tuple[str, re.Pattern, Handler, str]] = []

    def add(self, method: str, pattern: str, handler: Handler) -> None:
        full = self.prefix + pattern
        regex = re.compile("^" + _PARAM.sub(r"(?P<\1>[^/]+)", full) + "$")
        self.routes.append((method, regex, handler, full))

    def _decorator(self, method: str, pattern: str):
        def wrap(fn: Handler) -> Handler:
            self.add(method, pattern, fn)
            return fn
        return wrap

    def get(self, p): return self._decorator("GET", p)
    def post(self, p): return self._decorator("POST", p)
    def put(self, p): return self._decorator("PUT", p)
    def patch(self, p): return self._decorator("PATCH", p)
    def delete(self, p): return self._decorator("DELETE", p)

    def match(self, method: str, path: str) -> tuple[Handler, dict[str, str]]:
        allowed = False
        for m, regex, handler, _ in self.routes:
            hit = regex.match(path)
            if hit:
                if m == method:
                    return handler, {k: unquote(v) for k, v in hit.groupdict().items()}
                allowed = True
        if allowed:
            raise MethodNotAllowed(f"{method} is not allowed on {path}")
        raise NotFound(f"no API route {method} {path}")

    def describe(self) -> list[str]:
        return [f"{m:6} {full}" for m, _, _, full in self.routes]


class MethodNotAllowed(MakereelError):
    code, status = "method_not_allowed", 405


def parse_query(qs: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(qs).items()}
