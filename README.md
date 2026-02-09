# SnapTap

SnapTap is a small FastAPI app that downloads YouTube audio (MP3) or video (MP4) from one or many URLs. It provides a simple web UI plus JSON APIs for status and file download.

## Features
1. Paste multiple URLs (space or newline separated)
2. Choose MP3 or MP4
3. Live progress per item
4. Auto-download single files or a ZIP for multiple items
5. Recent job list with cleanup

## Quick Start
1. Create and activate a virtual environment.
2. Install dependencies:
```
pip install -r requirements.txt
```
3. Run the server:
```
uvicorn app:app --reload
```
4. Open `http://127.0.0.1:8000` in your browser.

## Environment Variables
Set these in your shell or in a `.env` file.

1. `YTDLP_COOKIES_FILE` (optional)
   Path to a cookies.txt file if you need authenticated access.
2. `MAX_RECENT` (default: 10)
   Number of recent jobs shown in the UI.
3. `JOB_TTL_HOURS` (default: 6)
   How long finished jobs and files are kept.
4. `CLEANUP_INTERVAL_MINUTES` (default: 30)
   How often cleanup runs.

## API
All APIs are served by `app.py`.

1. `POST /api/download`
   Body:
   ```
   {"urls": "https://youtu.be/... https://www.youtube.com/watch?v=...", "format": "mp3"}
   ```
   Returns:
   ```
   {"job_id": "<id>"}
   ```
2. `GET /api/status/{job_id}`
   Returns job status, per-item progress, and file names.
3. `GET /api/files/{job_id}/{file_index}`
   Downloads a single file.
4. `GET /api/files/{job_id}/zip`
   Downloads a ZIP of all files in the job.
5. `GET /api/recent`
   Returns a list of recent jobs for the UI.

## Notes
1. Downloads and ZIPs are stored under `tmp_downloads/<job_id>/` and are cleaned up automatically.
2. This tool uses `yt-dlp` and `static_ffmpeg` to handle media extraction and conversion.
3. Use only content you have the right to download.

