import os
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import static_ffmpeg
import yt_dlp

static_ffmpeg.add_paths()

ProgressHook = Callable[[int, str, dict[str, Any] | None], None]


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    if "youtube" not in parsed.netloc and "youtu.be" not in parsed.netloc:
        return url

    query = parse_qs(parsed.query)
    video_id = query.get("v", [None])[0]
    if video_id:
        clean_query = urlencode({"v": video_id})
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", clean_query, ""))

    return url


def _percent_from_progress(data: dict[str, Any]) -> float | None:
    total = data.get("total_bytes") or data.get("total_bytes_estimate")
    downloaded = data.get("downloaded_bytes")
    if total and downloaded:
        return round((downloaded / total) * 100, 2)
    return None


def download_media(
    video_urls: list[str] | str,
    mode: str = "mp3",
    output_folder: str = "downloads",
    progress_hook: ProgressHook | None = None,
) -> list[str]:
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    if mode not in {"mp3", "mp4"}:
        raise ValueError("mode must be 'mp3' or 'mp4'")

    ext = "mp3" if mode == "mp3" else "mp4"

    ydl_opts: dict[str, Any] = {
        "outtmpl": f"{output_folder}/%(title)s.%(ext)s",
        "quiet": False,
        "no_warnings": True,
    }

    if mode == "mp3":
        ydl_opts.update(
            {
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "320",
                    }
                ],
            }
        )
    else:
        ydl_opts.update(
            {
                "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "merge_output_format": "mp4",
            }
        )

    urls = video_urls if isinstance(video_urls, list) else [video_urls]
    urls = [_normalize_url(url) for url in urls]
    output_files: list[str] = []

    for index, video_url in enumerate(urls):
        def _progress(d: dict[str, Any]) -> None:
            if progress_hook and d.get("status") in {"downloading", "finished"}:
                info = dict(d)
                percent = _percent_from_progress(d)
                if percent is not None:
                    info["percent"] = percent
                progress_hook(index, d.get("status", "downloading"), info)

        ydl_opts["progress_hooks"] = [_progress]
        ydl_opts["noplaylist"] = True
        ydl_opts["http_headers"] = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
        cookies_file = os.getenv("YTDLP_COOKIES_FILE")
        if cookies_file:
            ydl_opts["cookiefile"] = cookies_file

        before_files = set(Path(output_folder).glob(f"*.{ext}"))

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(video_url, download=True)
        except Exception as exc:
            if progress_hook:
                progress_hook(index, "error", {"error": str(exc)})
            raise

        after_files = set(Path(output_folder).glob(f"*.{ext}"))
        new_files = [path for path in after_files - before_files if path.is_file()]
        if new_files:
            newest = max(new_files, key=lambda p: p.stat().st_mtime)
            output_files.append(str(newest))
            if progress_hook:
                progress_hook(index, "completed", {"filename": str(newest), "percent": 100})
        else:
            if progress_hook:
                progress_hook(index, "completed", {"percent": 100})

    return output_files


def download_audio_320kbps(video_urls: list[str] | str, output_folder: str = "downloads") -> list[str]:
    return download_media(video_urls, mode="mp3", output_folder=output_folder)


def download_video_mp4(video_urls: list[str] | str, output_folder: str = "video-downloads") -> list[str]:
    return download_media(video_urls, mode="mp4", output_folder=output_folder)


if __name__ == "__main__":
    url = [
        "https://www.youtube.com/watch?v=IMYs1X7HVbU",
    ]
    download_audio_320kbps(url)
