"""Trusted host controller. Credentials never enter the encoder container."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MAX_SOURCE_BYTES = 8 * 1024**3

class Client:
    def __init__(self, origin, job):
        parsed = urllib.parse.urlsplit(origin)
        if parsed.scheme != "https" or parsed.netloc != parsed.hostname or parsed.path or parsed.query or parsed.fragment:
            raise ValueError("Configure a canonical HTTPS Worker origin")
        if not re.fullmatch(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", job):
            raise ValueError("Invalid job ID")
        self.origin = origin
        self.base = origin + "/api/internal/downloads/" + job
        self.token = ""
        self.refresh_at = 0

    def identity(self):
        if time.monotonic() >= self.refresh_at:
            audience = self.origin + "/api/internal/media"
            url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&audience=" + urllib.parse.quote(audience, safe="")
            req = urllib.request.Request(url, headers={"Authorization": "Bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]})
            with urllib.request.urlopen(req, timeout=30) as response:
                self.token = json.load(response)["value"]
            # Redact every refreshed identity token in Actions logs.
            print("::add-mask::" + self.token, flush=True)
            self.refresh_at = time.monotonic() + 180
        return self.token

    def request(self, action, method="POST", payload=None, file=None, relative=None):
        url = self.base + "/" + action
        if relative:
            url += "?path=" + urllib.parse.quote(relative, safe="")
        for attempt in range(10 if action == "complete" else 4):
            headers = {"Authorization": "Bearer " + self.identity()}
            stream = None
            if file:
                headers.update({"Content-Length": str(file.stat().st_size), "Content-Type": "application/octet-stream"})
                stream = file.open("rb")
                data = stream
            else:
                data = json.dumps(payload).encode() if payload is not None else None
                if data is not None:
                    headers["Content-Type"] = "application/json"
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                # Reject redirects so tokens cannot be forwarded to other origins.
                opener = urllib.request.build_opener(NoRedirect())
                return opener.open(req, timeout=300)
            except urllib.error.HTTPError as exc:
                if exc.code == 409 and action == "complete" and attempt < 9:
                    time.sleep(min(30, 2 ** attempt))
                    continue
                if exc.code < 500:
                    raise RuntimeError("Worker rejected " + action + " (" + str(exc.code) + ")") from None
                if attempt == 3:
                    raise RuntimeError("Worker unavailable for " + action) from None
            except (OSError, TimeoutError):
                if attempt == 3:
                    raise RuntimeError("Network failure during " + action) from None
            finally:
                if stream:
                    stream.close()
            time.sleep(2 ** attempt)

    def post(self, action, payload):
        with self.request(action, payload=payload) as response:
            return json.load(response)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def artifact_path(path):
    return path in ("master.m3u8", "thumbnails/poster.jpg") or bool(re.fullmatch(r"(360p|480p|720p|1080p)/(index\.m3u8|segment_\d{5,}\.ts)", path))

def validate_source(value):
    import socket
    import ipaddress
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Invalid download URL")
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Initial source must resolve to public addresses")
    return value

def main():
    client = Client(os.environ["MEDIA_WORKER_ORIGIN"], os.environ["MEDIA_JOB_ID"])
    claimed = False
    process = None
    try:
        job = client.post("claim", {})
        claimed = True
        url = validate_source(job["url"])
        height = job.get("maxHeight") or 1080
        if height not in (360, 480, 720, 1080):
            raise ValueError("Unsupported quality")
        with tempfile.TemporaryDirectory(prefix="animezak-download-") as temporary:
            output = Path(temporary) / "video.%(ext)s"
            # Child network code receives no Actions identity or repository credentials.
            environment = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")}
            command = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist",
                       "--max-downloads", "1", "--max-filesize", "90M", "--socket-timeout", "30",
                       "--retries", "3", "--fragment-retries", "3", "--quiet", "--no-warnings",
                       "--no-progress", "--restrict-filenames", "--no-write-info-json",
                       "--no-write-thumbnail", "--js-runtimes", "node",
                       "-f", f"bestvideo[height<={height}]+bestaudio/best[height<={height}]",
                       "--merge-output-format", "mp4", "--remux-video", "mp4",
                       "-o", str(output), "--", url]
            process = subprocess.Popen(command, env=environment, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, start_new_session=True)
            started = time.monotonic()
            while process.poll() is None:
                if time.monotonic() - started > 1500:
                    raise RuntimeError("Download timeout")
                client.post("progress", {"progress": 0})
                time.sleep(20)
            if process.returncode not in (0, 101):
                raise RuntimeError("Download failed")
            file = Path(temporary) / "video.mp4"
            if not file.is_file() or not 0 < file.stat().st_size <= 90 * 1024**2:
                raise RuntimeError("Missing or oversized video")
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                                    "-of", "json", str(file)], capture_output=True, timeout=30)
            if probe.returncode or not any(s.get("codec_type") == "video" for s in json.loads(probe.stdout)["streams"]):
                raise RuntimeError("Output is not a video")
            with client.request("file", method="PUT", file=file):
                pass
            claimed = False
    finally:
        if process is not None and process.poll() is None:
            import signal
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=30)
        if claimed:
            try:
                client.post("fail", {})
            except Exception:
                pass

if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Video download failed. Check source support, runner setup and limits.", file=sys.stderr)
        sys.exit(1)
