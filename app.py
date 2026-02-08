from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
import threading
import time
import zipfile
import unicodedata
import re
import os

from fastapi import BackgroundTasks, Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from helper import download_media

app = FastAPI(title="yt2mp3")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "tmp_downloads"
DATA_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()
MAX_RECENT = int(os.getenv("MAX_RECENT", 10))
JOB_TTL_HOURS = int(os.getenv("JOB_TTL_HOURS", 6))
CLEANUP_INTERVAL_MINUTES = int(os.getenv("CLEANUP_INTERVAL_MINUTES", 30))


def _safe_filename(name: str, fallback: str = "download") -> str:
    if not name:
        return fallback
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", ascii_name)
    ascii_name = ascii_name.strip("._-")
    return ascii_name or fallback


def _parse_urls(raw: str) -> list[str]:
    if not raw:
        return []
    lines = [line.strip() for line in raw.splitlines()]
    tokens: list[str] = []
    for line in lines:
        if not line:
            continue
        tokens.extend(line.split())
    return [t for t in tokens if t]


def _new_job(urls: list[str], fmt: str) -> str:
    job_id = uuid4().hex
    now = datetime.utcnow()
    job = {
        "id": job_id,
        "status": "queued",
        "format": fmt,
        "urls": urls,
        "items": [{"url": url, "status": "queued", "percent": 0} for url in urls],
        "files": [],
        "error": None,
        "created_at": now.isoformat() + "Z",
        "updated_at": now.isoformat() + "Z",
        "created_ts": now.timestamp(),
    }
    with _jobs_lock:
        _jobs[job_id] = job
    return job_id


def _update_job(job_id: str, **updates: Any) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.update(updates)
        job["updated_at"] = datetime.utcnow().isoformat() + "Z"


def _download_job(job_id: str) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return

    output_dir = DATA_DIR / job_id
    output_dir.mkdir(exist_ok=True)

    def progress_hook(item_index: int, status: str, info: dict[str, Any] | None = None) -> None:
        with _jobs_lock:
            job_local = _jobs.get(job_id)
            if not job_local:
                return
            items = job_local["items"]
            if 0 <= item_index < len(items):
                items[item_index]["status"] = status
            if info:
                if "filename" in info:
                    items[item_index]["filename"] = Path(info["filename"]).name
                if "percent" in info:
                    items[item_index]["percent"] = info["percent"]

    _update_job(job_id, status="running")
    try:
        files = download_media(
            job["urls"],
            mode=job["format"],
            output_folder=str(output_dir),
            progress_hook=progress_hook,
        )
        _update_job(job_id, status="finished", files=files)
    except Exception as exc:
        _update_job(job_id, status="error", error=str(exc))


def _cleanup_old_jobs() -> None:
    cutoff = datetime.utcnow() - timedelta(hours=JOB_TTL_HOURS)
    cutoff_ts = cutoff.timestamp()
    to_remove: list[tuple[str, Path]] = []
    with _jobs_lock:
        for job_id, job in list(_jobs.items()):
            created_ts = job.get("created_ts", 0)
            if created_ts and created_ts < cutoff_ts:
                to_remove.append((job_id, DATA_DIR / job_id))
                _jobs.pop(job_id, None)
    for job_id, path in to_remove:
        if path.exists():
            for child in path.glob("*"):
                try:
                    child.unlink()
                except OSError:
                    pass
            try:
                path.rmdir()
            except OSError:
                pass
        zip_path = DATA_DIR / f"{job_id}.zip"
        if zip_path.exists():
            try:
                zip_path.unlink()
            except OSError:
                pass


def _cleanup_loop() -> None:
    while True:
        _cleanup_old_jobs()
        time.sleep(CLEANUP_INTERVAL_MINUTES * 60)


@app.on_event("startup")
def _start_cleanup() -> None:
    thread = threading.Thread(target=_cleanup_loop, daemon=True)
    thread.start()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/download")
def api_download(
    background_tasks: BackgroundTasks,
    payload: dict[str, Any] = Body(...),
):
    urls = _parse_urls(payload.get("urls", ""))
    fmt = payload.get("format", "mp3")
    if not urls:
        raise HTTPException(status_code=400, detail="Please provide at least one valid URL.")
    if fmt not in {"mp3", "mp4"}:
        raise HTTPException(status_code=400, detail="Unsupported format. Choose mp3 or mp4.")

    job_id = _new_job(urls, fmt)
    background_tasks.add_task(_download_job, job_id)
    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
def api_status(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    response = {
        "id": job["id"],
        "status": job["status"],
        "format": job["format"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "items": job["items"],
        "error": job["error"],
        "files": [Path(p).name for p in job["files"]],
    }
    return JSONResponse(response)


@app.get("/api/recent")
def api_recent():
    with _jobs_lock:
        recent = list(_jobs.values())
    recent.sort(key=lambda j: j["created_at"], reverse=True)
    recent = recent[:MAX_RECENT]
    payload = [
        {
            "id": job["id"],
            "status": job["status"],
            "format": job["format"],
            "created_at": job["created_at"],
            "url_count": len(job["urls"]),
        }
        for job in recent
    ]
    return JSONResponse(payload)


def _build_zip(job_id: str, files: list[str]) -> Path:
    zip_path = DATA_DIR / f"{job_id}.zip"
    if zip_path.exists():
        return zip_path
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file_path in files:
            path = Path(file_path)
            if path.exists():
                zipf.write(path, arcname=path.name)
    return zip_path


@app.get("/api/files/{job_id}/zip")
def api_zip(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.get("status") != "finished":
        raise HTTPException(status_code=400, detail="Job not finished yet.")
    files = job.get("files", [])
    if not files:
        raise HTTPException(status_code=404, detail="No files to zip.")

    zip_path = _build_zip(job_id, files)
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="Zip file not found.")

    return FileResponse(
        path=str(zip_path),
        filename=f"{job_id}.zip",
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=\"{job_id}.zip\""
        },
    )


@app.get("/api/files/{job_id}/{file_index}")
def api_files(job_id: str, file_index: int):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    files = job.get("files", [])
    if file_index < 0 or file_index >= len(files):
        raise HTTPException(status_code=404, detail="File not found.")

    file_path = Path(files[file_index])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found.")

    return FileResponse(
        path=str(file_path),
        filename=_safe_filename(file_path.name),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename=\"{_safe_filename(file_path.name)}\""
        },
    )
