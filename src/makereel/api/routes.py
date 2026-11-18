"""REST API v1. Every response is JSON; errors are {"error": {"code", "message", "hint"}}.

See docs/API.md for request and response examples.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from .. import __version__
from ..config import env, load_settings, save_settings
from ..core import media, models, sources
from ..errors import InvalidInput
from ..services import bench, brand, library, updates
from ..services.jobs import JobManager
from ..services.watcher import Watcher
from .router import Request, Response, Router

MAX_UPLOAD_BYTES = 8 * 1024**3
UPLOAD_OPTIONS = ("title", "credit", "credit_url", "profile", "max_clips", "min_len", "max_len",
                  "model", "model_other", "language", "layout", "fps")


def _read_all(req: Request, limit: int) -> bytes:
    if not 0 < req.length <= limit:
        raise InvalidInput(f"the file is empty or larger than {limit // 1024**2} MB")
    return req.stream.read(req.length)


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
        offset = body.get("offset")
        try:
            offset = float(offset) if offset not in (None, "") else None
        except (TypeError, ValueError) as e:
            raise InvalidInput("offset must be a number of seconds") from e
        return library.update_reel(req.params["folder"], req.params["name"],
                                   hook=body.get("hook"), caption=body.get("caption"),
                                   transcript=body.get("transcript"), words=body.get("words"), offset=offset,
                                   ass=body.get("ass"), logo=body.get("logo"), restyle=bool(body.get("restyle")),
                                   look=body.get("look"), fit=body.get("fit"), cards=body.get("cards"),
                                   camera=body.get("camera"))

    @api.post("/folders/{folder}/reels/{name}/import")
    def import_captions(req: Request):
        return library.import_captions(req.params["folder"], req.params["name"], str(req.json().get("text") or ""))

    @api.post("/folders/{folder}/reels/{name}/sync")
    def sync_reel(req: Request):
        return library.autosync(req.params["folder"], req.params["name"])

    @api.post("/folders/{folder}/reels/{name}/trim")
    def trim_reel(req: Request):
        body = req.json()
        try:
            start, end = float(body.get("start") or 0), float(body.get("end") or 0)
        except (TypeError, ValueError) as e:
            raise InvalidInput("start and end are seconds to move each edge, e.g. -2 or 1.5") from e
        return library.trim_reel(req.params["folder"], req.params["name"], start, end)

    @api.post("/folders/{folder}/reels/{name}/split")
    def split_reel(req: Request):
        try:
            at = float(req.json().get("at"))
        except (TypeError, ValueError) as e:
            raise InvalidInput("give the split point in seconds, e.g. {\"at\": 12.5}") from e
        return library.split_reel(req.params["folder"], req.params["name"], at)

    @api.post("/folders/{folder}/merge")
    def merge(req: Request):
        names = req.json().get("reels")
        if not isinstance(names, list):
            raise InvalidInput('give the reels to join in order, e.g. {"reels": ["reel_01", "reel_03"]}')
        return Response(library.merge_reels(req.params["folder"], [str(n) for n in names]), 201)

    @api.post("/folders/{folder}/reels/{name}/export")
    def export_reel(req: Request):
        body = req.json()
        return library.export_reel(req.params["folder"], req.params["name"], body.get("format", ""), body.get("fit"))

    @api.delete("/folders/{folder}/reels/{name}")
    def delete_reel(req: Request):
        library.delete_reel(req.params["folder"], req.params["name"])
        return Response(None, 204)

    # ------------------------------------------------------------ benchmarks
    @api.get("/bench")
    def bench_history(req: Request):
        runs = bench.history()
        return {"device": bench.device_profile(), "runs": runs[:50],
                "share_enabled": bool(bench.REPO_URL)}

    @api.post("/bench")
    def bench_start(req: Request):
        body = req.json()
        return Response(jobs.submit_bench({k: body.get(k) for k in ("video", "model")}).to_dict(), 201)

    @api.get("/bench/{result_id}")
    def bench_result(req: Request):
        result = bench.get(req.params["result_id"])
        return {**result, "compare": bench.compare(result), "report": bench.report_markdown(result),
                "share_url": bench.share_url(result)}

    # ------------------------------------------------------------ brand kit
    @api.get("/brand")
    def brand_get(req: Request):
        return {**brand.info(), "settings": load_settings().brand}

    @api.put("/brand/logo")
    def brand_logo(req: Request):
        return brand.save_logo(_read_all(req, brand.MAX_LOGO_BYTES))

    @api.delete("/brand/logo")
    def brand_logo_delete(req: Request):
        brand.delete_logo()
        return brand.info()

    @api.put("/brand/fonts/{name}")
    def brand_font(req: Request):
        return brand.save_font(req.params["name"], _read_all(req, brand.MAX_FONT_BYTES))

    @api.delete("/brand/fonts/{name}")
    def brand_font_delete(req: Request):
        brand.delete_font(req.params["name"])
        return brand.info()

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

    # ------------------------------------------------------------ first-run setup: speech models
    @api.get("/setup")
    def get_setup(req: Request):
        focus = req.query.get("focus") or "both"
        if focus not in models.FOCUS:
            raise InvalidInput("focus must be english, indian or both")
        pc = models.computer()
        settings = load_settings()
        return {"computer": pc, "recommended": models.recommend(pc, focus), "models": models.catalog(),
                "current": {"model": settings.clip["model"], "model_other": settings.clip["model_other"],
                            "device": settings["speech_device"]}, "setup_done": settings["setup_done"]}

    @api.post("/setup/models/{name}")
    def download_model(req: Request):
        if req.params["name"] not in models.CATALOG:
            raise InvalidInput("unknown speech model")
        return models.download(req.params["name"])

    # ------------------------------------------------------------ updates from GitHub releases
    def busy() -> bool:
        return any(j["status"] in ("queued", "running", "live") and j["kind"] != "watcher" for j in jobs.list())

    @api.get("/updates")
    def get_updates(req: Request):
        return updates.check(force=req.query.get("force") == "1")

    @api.post("/updates/install")
    def install_update(req: Request):
        return updates.install(busy())

    @api.post("/updates/restart")
    def restart(req: Request):
        if busy():
            raise InvalidInput("reels are being made or recorded; restart when they're done")
        updates.restart()
        return {"restarting": True}

    return api
