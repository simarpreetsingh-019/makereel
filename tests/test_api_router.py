import pytest

from makereel.api.router import MethodNotAllowed, Router
from makereel.errors import NotFound


def test_match_params_and_methods():
    r = Router("/api/v1")
    r.get("/folders/{folder}/reels/{name}")(lambda req: "get")
    r.patch("/folders/{folder}/reels/{name}")(lambda req: "patch")
    handler, params = r.match("PATCH", "/api/v1/folders/Me%20at%20the%20zoo/reels/reel_01")
    assert handler(None) == "patch" and params == {"folder": "Me at the zoo", "name": "reel_01"}
    with pytest.raises(MethodNotAllowed):
        r.match("POST", "/api/v1/folders/x/reels/y")
    with pytest.raises(NotFound):
        r.match("GET", "/api/v1/nope")
