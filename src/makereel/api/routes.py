"""REST API v1. Every response is JSON; errors are {"error": {"code", "message", "hint"}}.

See docs/API.md for request and response examples.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from .. import __version__
from ..config import env, load_settings, save_settings
from ..core import media, sources
from ..errors import InvalidInput
from ..services import library
from ..services.jobs import JobManager
from ..services.watcher import Watcher
from .router import Request, Response, Router

MAX_UPLOAD_BYTES = 8 * 1024**3
UPLOAD_OPTIONS = ("title", "credit", "credit_url", "profile", "max_clips", "min_len", "max_len",
                  "model", "language", "layout")


def build(jobs: JobManager, watcher: Watcher) -> Router:
    api = Router("/api/v1")

    # ------------------------------------------------------------ system
    @api.get("/health")
    def health(req: Request):
        return {"ok": True, "version": __version__}

    @api.get("/system")
    def system(req: Request):
        return {**media.system_info(), "version": __version__}

    # ------------------------------------------------------------ jobs
    @api.get("/jobs")
    def list_jobs(req: Request):
        return {"jobs": jobs.list()}

    @api.post("/jobs")
    def create_job(req: Request):
        body = req.json()
        url = sources.validate_url(body.get("url", ""))
        if body.get("section"):
            sources.parse_section(body["section"])  # fail fast on a bad range
        return Response(jobs.submit_link(url, body).to_dict(), 201)

    @api.post("/jobs/upload")
    def upload(req: Request):
        """Body is the raw file (no multipart); options go in the query string."""
        if not 0 < req.length <= MAX_UPLOAD_BYTES:
            raise InvalidInput("the file is empty or larger than 8 GB")
        name = re.sub(r"[^\w.\-]", "_", Path(req.query.get("name", "upload.mp4")).name)[-80:]
        dest = env().work_dir / "uploads" / f"{uuid.uuid4().hex[:6]}_{name}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        left = req.length
        with dest.open("wb") as f:
            while left:
                chunk = req.stream.read(min(1 << 20, left))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        if left:
            dest.unlink(missing_ok=True)
            raise InvalidInput("the upload was interrupted")
        options = {k: req.query[k] for k in UPLOAD_OPTIONS if req.query.get(k)}
        options.setdefault("title", Path(name).stem.split("_", 1)[-1])
        return Response(jobs.submit_file(dest, options).to_dict(), 201)

    @api.get("/jobs/{job_id}")
    def get_job(req: Request):
        return jobs.get(req.params["job_id"]).to_dict(with_log=True)

    @api.post("/jobs/{job_id}/stop")
    def stop_job(req: Request):
        return jobs.stop(req.params["job_id"]).to_dict()

    # ------------------------------------------------------------ library
    @api.get("/folders")
    def folders(req: Request):
        return {"folders": library.list_folders()}

    @api.get("/folders/{folder}")
    def folder(req: Request):
        return library.list_reels(req.params["folder"])

    @api.delete("/folders/{folder}")
    def delete_folder(req: Request):
        library.delete_folder(req.params["folder"])
        return Response(None, 204)

    @api.get("/folders/{folder}/reels/{name}")
    def get_reel(req: Request):
        return library.get_reel(req.params["folder"], req.params["name"])

    @api.patch("/folders/{folder}/reels/{name}")
    def edit_reel(req: Request):
        body = req.json()
        return library.update_reel(req.params["folder"], req.params["name"],
                                   hook=body.get("hook"), caption=body.get("caption"),
                                   transcript=body.get("transcript"), ass=body.get("ass"))

    @api.delete("/folders/{folder}/reels/{name}")
    def delete_reel(req: Request):
        library.delete_reel(req.params["folder"], req.params["name"])
        return Response(None, 204)

    # ------------------------------------------------------------ settings + watcher
    @api.get("/settings")
    def get_settings(req: Request):
        return load_settings().data

    @api.put("/settings")
    def put_settings(req: Request):
        return save_settings(req.json()).data

    @api.get("/watcher")
    def get_watcher(req: Request):
        return {"running": watcher.running}

    @api.put("/watcher")
    def put_watcher(req: Request):
        if req.json().get("running"):
            watcher.start()
        else:
            watcher.stop()
        return {"running": watcher.running}

    return api
