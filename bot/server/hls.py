import asyncio
import json
import math
import re
import shutil
from pathlib import Path
from urllib.parse import quote

import imageio_ffmpeg
from aiohttp import web

CACHE_ROOT = Path("cache") / "hls"
CACHE_ROOT.mkdir(parents=True, exist_ok=True)
SEGMENT_TIME = 6
MAX_RENDITIONS = [1080, 720, 480]


class HLSManager:
    def __init__(self):
        self._locks = {}

    def _token(self, chat_id: int, message_id: int, secure_hash: str) -> str:
        return f"{abs(chat_id)}_{message_id}_{secure_hash}"

    def _session_dir(self, token: str) -> Path:
        return CACHE_ROOT / token

    async def ensure_stream(self, *, base_url: str, chat_id: int, message_id: int, secure_hash: str, file_name: str | None = None):
        token = self._token(chat_id, message_id, secure_hash)
        session_dir = self._session_dir(token)
        master = session_dir / "master.m3u8"
        meta_path = session_dir / "meta.json"
        if master.exists() and meta_path.exists():
            return token, json.loads(meta_path.read_text())

        lock = self._locks.setdefault(token, asyncio.Lock())
        async with lock:
            if master.exists() and meta_path.exists():
                return token, json.loads(meta_path.read_text())
            if session_dir.exists():
                shutil.rmtree(session_dir, ignore_errors=True)
            session_dir.mkdir(parents=True, exist_ok=True)

            source_name = quote(file_name or f"video-{message_id}.mp4")
            source_url = f"{base_url}/{str(chat_id).replace('-100', '')}/{source_name}?id={message_id}&hash={secure_hash}"
            probe = await self._probe_stream(source_url)
            renditions = self._build_renditions(probe)
            audio_tracks = probe.get("audio_tracks", [])
            await self._generate_hls(source_url, session_dir, renditions, audio_tracks)
            self._write_master_playlist(session_dir, token, renditions, audio_tracks)
            meta = {"renditions": renditions, "audio_tracks": audio_tracks, "duration": probe.get("duration")}
            meta_path.write_text(json.dumps(meta))
            return token, meta

    async def _probe_stream(self, source_url: str):
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        process = await asyncio.create_subprocess_exec(
            ffmpeg,
            "-hide_banner",
            "-i",
            source_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        output = stderr.decode("utf-8", errors="ignore")

        video_match = re.search(r"Video: .*?, .*?, (\d+)x(\d+)", output)
        width = int(video_match.group(1)) if video_match else 1280
        height = int(video_match.group(2)) if video_match else 720
        duration_match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", output)
        duration = None
        if duration_match:
            hours, minutes, seconds = duration_match.groups()
            duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)

        audio_tracks = []
        for idx, match in enumerate(re.finditer(r"Stream #0:(\d+)(?:\(([^)]+)\))?: Audio: ([^,]+)", output)):
            stream_index, language, codec = match.groups()
            audio_tracks.append(
                {
                    "stream_index": int(stream_index),
                    "language": (language or f"track-{idx + 1}").lower(),
                    "label": (language or f"Audio {idx + 1}").upper(),
                    "codec": codec,
                    "default": idx == 0,
                }
            )
        return {"width": width, "height": height, "duration": duration, "audio_tracks": audio_tracks}

    def _build_renditions(self, probe: dict):
        width = probe["width"]
        height = probe["height"]
        aspect = width / height if width and height else 16 / 9
        bitrate_table = {1080: 5000, 720: 2800, 480: 1400}
        renditions = []
        for target_h in MAX_RENDITIONS:
            if target_h > height:
                continue
            target_w = math.floor((target_h * aspect) / 2) * 2
            renditions.append(
                {
                    "name": f"{target_h}p",
                    "width": max(target_w, 320),
                    "height": target_h,
                    "bandwidth": bitrate_table[target_h] * 1000,
                    "bitrate": f"{bitrate_table[target_h]}k",
                    "maxrate": f"{int(bitrate_table[target_h] * 1.07)}k",
                    "bufsize": f"{bitrate_table[target_h] * 2}k",
                }
            )
        if not renditions:
            renditions.append({"name": f"{height}p", "width": width, "height": height, "bandwidth": 1800000, "bitrate": "1800k", "maxrate": "1926k", "bufsize": "3600k"})
        return renditions

    async def _run_ffmpeg(self, *args):
        process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(stderr.decode("utf-8", errors="ignore"))

    async def _generate_hls(self, source_url: str, session_dir: Path, renditions: list[dict], audio_tracks: list[dict]):
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        tasks = []
        for rendition in renditions:
            out_dir = session_dir / rendition["name"]
            out_dir.mkdir(parents=True, exist_ok=True)
            tasks.append(
                self._run_ffmpeg(
                    ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", source_url,
                    "-map", "0:v:0", "-an",
                    "-vf", f"scale=w={rendition['width']}:h={rendition['height']}:force_original_aspect_ratio=decrease,pad={rendition['width']}:{rendition['height']}:(ow-iw)/2:(oh-ih)/2",
                    "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "main",
                    "-crf", "21", "-sc_threshold", "0", "-g", "48", "-keyint_min", "48",
                    "-b:v", rendition["bitrate"], "-maxrate", rendition["maxrate"], "-bufsize", rendition["bufsize"],
                    "-hls_time", str(SEGMENT_TIME), "-hls_playlist_type", "vod", "-hls_segment_type", "fmp4",
                    "-hls_flags", "independent_segments",
                    "-hls_segment_filename", str(out_dir / "segment_%03d.m4s"),
                    str(out_dir / "index.m3u8"),
                )
            )
        for audio in audio_tracks:
            out_dir = session_dir / f"audio_{audio['language']}"
            out_dir.mkdir(parents=True, exist_ok=True)
            tasks.append(
                self._run_ffmpeg(
                    ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", source_url,
                    "-map", f"0:a:{audio['stream_index'] - 1 if audio['stream_index'] > 0 else 0}", "-vn",
                    "-c:a", "aac", "-b:a", "128k",
                    "-hls_time", str(SEGMENT_TIME), "-hls_playlist_type", "vod", "-hls_segment_type", "fmp4",
                    "-hls_flags", "independent_segments",
                    "-hls_segment_filename", str(out_dir / "segment_%03d.m4s"),
                    str(out_dir / "index.m3u8"),
                )
            )
        await asyncio.gather(*tasks)

    def _write_master_playlist(self, session_dir: Path, token: str, renditions: list[dict], audio_tracks: list[dict]):
        lines = ["#EXTM3U", "#EXT-X-VERSION:7"]
        if audio_tracks:
            for audio in audio_tracks:
                lines.append(
                    f'#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="{audio["label"]}",LANGUAGE="{audio["language"]}",DEFAULT={"YES" if audio["default"] else "NO"},AUTOSELECT=YES,URI="{token}/audio_{audio["language"]}/index.m3u8"'
                )
        for rendition in renditions:
            attrs = [
                f'BANDWIDTH={rendition["bandwidth"]}',
                f'RESOLUTION={rendition["width"]}x{rendition["height"]}',
                'CODECS="avc1.64001f,mp4a.40.2"',
            ]
            if audio_tracks:
                attrs.append('AUDIO="audio"')
            lines.append(f"#EXT-X-STREAM-INF:{','.join(attrs)}")
            lines.append(f"{token}/{rendition['name']}/index.m3u8")
        (session_dir / "master.m3u8").write_text("\n".join(lines) + "\n")

    async def serve_path(self, token: str, tail: str):
        target = (self._session_dir(token) / tail).resolve()
        root = self._session_dir(token).resolve()
        if root not in target.parents and target != root:
            raise web.HTTPForbidden(text="Invalid HLS path")
        if not target.exists():
            raise web.HTTPNotFound(text="HLS asset not found")
        response = web.FileResponse(target)
        if target.suffix == ".m3u8":
            response.content_type = "application/vnd.apple.mpegurl"
        elif target.suffix == ".m4s":
            response.content_type = "video/iso.segment"
        return response


hls_manager = HLSManager()
