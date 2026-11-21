"""REST API v1. Every response is JSON; errors are {"error": {"code", "message", "hint"}}.

See docs/API.md for request and response examples.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from .. import __version__
from ..config import load_settings, save_settings, work_dir
from ..core import media, models, sources
from ..errors import InvalidInput
from ..services import bench, brand, library, storage, updates, youtube
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

    @api.get("/system/load")
    def system_load(req: Request):
        from ..core import sysmon
        return sysmon.snapshot()

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
        dest = work_dir() / "uploads" / f"{uuid.uuid4().hex[:6]}_{name}"
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

    @api.delete("/jobs/{job_id}")
    def remove_job(req: Request):
        jobs.remove(req.params["job_id"])
        return {"removed": req.params["job_id"]}

    @api.post("/jobs/clear")
    def clear_jobs(req: Request):
        return {"cleared": jobs.clear_finished()}

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

    @api.put("/folders/{folder}/reels/{name}/ready")
    def reel_ready(req: Request):
        return library.set_ready(req.params["folder"], req.params["name"], bool(req.json().get("ready")))

    @api.post("/folders/{folder}/reels/{name}/compare")
    def reel_compare(req: Request):
        body = req.json()
        return library.compare_with_text(req.params["folder"], req.params["name"], body.get("text", ""),
                                         body.get("label", ""))

    @api.post("/folders/{folder}/reels/{name}/use-other")
    def reel_use_other(req: Request):
        return library.use_other_version(req.params["folder"], req.params["name"])

    @api.post("/folders/{folder}/reels/{name}/ai-fix")
    def reel_ai_fix(req: Request):
        return library.ai_fix_words(req.params["folder"], req.params["name"])

    @api.get("/creators")
    def creators_list(req: Request):
        from ..services import creators
        return {"creators": creators.channels()}

    @api.get("/creators/{channel}")
    def creator_get(req: Request):
        from ..services import creators
        ch = req.params["channel"]
        return {**creators.load(ch), "suggested": creators.suggest(ch) if req.query.get("suggest") else []}

    @api.put("/creators/{channel}")
    def creator_put(req: Request):
        from ..services import creators
        body = req.json()
        names = body.get("names") or []
        if not isinstance(names, list):
            raise InvalidInput("names must be a list")
        return creators.save(req.params["channel"], [str(n) for n in names], str(body.get("notes") or ""))

    @api.post("/folders/{folder}/youtube-captions")
    def folder_youtube_captions(req: Request):
        return library.youtube_upgrade(req.params["folder"])

    @api.post("/folders/{folder}/zip")
    def folder_zip(req: Request):
        return library.folder_zip(req.params["folder"])

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

    @api.post("/folders/{folder}/reels/{name}/shorts")
    def make_shorts(req: Request):
        body = req.json()
        try:
            length, count = float(body.get("length", 45)), int(body.get("count", 3))
        except (TypeError, ValueError) as e:
            raise InvalidInput("length and count must be numbers") from e
        return library.short_versions(req.params["folder"], req.params["name"], length, count)

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
        body = req.json()
        settings = save_settings(body)
        if "cpu_mode" in body:
            media.apply_priority()
        return settings.data

    @api.get("/watcher")
    def get_watcher(req: Request):
        return {"running": watcher.running, "channels": watcher.channel_state}

    @api.put("/watcher")
    def put_watcher(req: Request):
        on = bool(req.json().get("running"))
        if on:
            watcher.start()
        else:
            watcher.stop()
        save_settings({"watching": on})          # remembered: it comes back on when makereel restarts
        return {"running": watcher.running}

    # ------------------------------------------------------------ YouTube's "are you a bot?" check
    @api.get("/youtube/sign-in")
    def youtube_sign_in(req: Request):
        return sources.check_sign_in()

    @api.post("/youtube/open")
    def youtube_open(req: Request):
        return youtube.open_youtube(str(req.json().get("browser", "")))

    @api.put("/youtube/cookies")
    def youtube_cookies(req: Request):
        return youtube.save_cookies(req.body)

    @api.delete("/youtube/cookies")
    def youtube_cookies_remove(req: Request):
        return youtube.remove_cookies()

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

    @api.post("/setup/models/{name}/cancel")
    def cancel_model(req: Request):
        if req.params["name"] not in models.CATALOG:
            raise InvalidInput("unknown speech model")
        return models.cancel(req.params["name"])

    @api.delete("/setup/models/{name}")
    def delete_model(req: Request):
        name = req.params["name"]
        if name not in models.CATALOG:
            raise InvalidInput("unknown speech model")
        clip = load_settings().clip
        if name in (clip["model"], clip["model_other"]):
            raise InvalidInput(f"{name} is in use for new reels",
                               "Pick other models and save first, then delete this one.")
        return models.delete(name)

    def busy() -> bool:
        return any(j["status"] in ("queued", "running", "live") and j["kind"] != "watcher" for j in jobs.list())

    # ------------------------------------------------------------ where files are saved, and the cache
    @api.get("/storage")
    def get_storage(req: Request):
        return storage.info()

    @api.post("/storage/open")
    def open_storage(req: Request):
        body = req.json()
        return storage.open_folder(str(body.get("which", "reels")), body.get("folder") or None)

    @api.post("/storage/clear-cache")
    def clear_cache(req: Request):
        recording = {j.session.info.id for j in (jobs.get(x["id"]) for x in jobs.list() if x["status"] == "live")
                     if j.session is not None}
        return storage.clear_cache(recording)

    @api.put("/storage/reels-folder")
    def set_reels_folder(req: Request):
        body = req.json()
        if body.get("move") and busy():
            raise InvalidInput("reels are being made or recorded right now",
                               "Move the reels when nothing is running, so no reel is left half-written.")
        return storage.move_reels(str(body.get("path") or ""), bool(body.get("move")))

    # ------------------------------------------------------------ updates from GitHub releases

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
