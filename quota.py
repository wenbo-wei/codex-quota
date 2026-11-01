#!/usr/bin/python3
"""Update the GNOME quota panel every minute, with fast startup retries."""

import json
import math
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

import dbus

CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
CODEX_BIN = os.environ.get("CODEX_BIN") or shutil.which("codex") or str(Path.home() / ".local/bin/codex")
STATE_FILE = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "codex-quota.json"


def weekly_remaining(result):
    if not isinstance(result, dict):
        return None
    rate = result.get("rateLimits")
    if not isinstance(rate, dict) or rate.get("limitId") != "codex":
        buckets = result.get("rateLimitsByLimitId")
        rate = buckets.get("codex") if isinstance(buckets, dict) else None
    if not isinstance(rate, dict) or rate.get("limitId") not in (None, "codex"):
        return None
    for name in ("primary", "secondary"):
        window = rate.get(name)
        if not isinstance(window, dict) or window.get("windowDurationMins") != 10080:
            continue
        used = window.get("usedPercent")
        if type(used) in (int, float) and math.isfinite(used):
            return 100.0 - max(0.0, min(100.0, used))
    return None


def account_identity():
    try:
        stat = (CODEX_HOME / "auth.json").stat()
        return stat.st_ino, stat.st_mtime_ns, stat.st_size
    except OSError:
        return None


def read_weekly(stop, *, codex_bin=CODEX_BIN, timeout=10):
    """Make one bounded request; discard results if the login changed."""
    if stop.is_set():
        return None
    identity = account_identity()
    process = None
    deadline = time.monotonic() + timeout
    try:
        process = subprocess.Popen(
            [str(codex_bin), "app-server", "--stdio"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            bufsize=0, start_new_session=True,
        )
        for message in (
            {"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "codex-quota", "version": "1.0"}}},
            {"method": "initialized"},
            {"id": 2, "method": "account/rateLimits/read"},
        ):
            process.stdin.write((json.dumps(message) + "\n").encode())
        buffer = b""
        while not stop.is_set() and time.monotonic() < deadline:
            if not select.select([process.stdout], [], [], 0.1)[0]:
                continue
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                break
            buffer += chunk
            if len(buffer) > 1024 * 1024:
                break
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                try:
                    response = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                if isinstance(response, dict) and response.get("id") == 2:
                    return weekly_remaining(response.get("result")) if identity == account_identity() else None
    except OSError:
        pass
    finally:
        if process is not None:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=0.2)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            process.stdin.close()
            process.stdout.close()
    return None


def write_state_file(payload, path=STATE_FILE):
    """Replace the private file atomically, without keeping a cache."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def publish(bus, remaining):
    payload = json.dumps({"remaining_percent": remaining}, separators=(",", ":"), allow_nan=False)
    try:
        write_state_file(payload)
    except OSError as error:
        print(f"codex-quota: {error}", file=sys.stderr)
    try:
        bus.call_blocking(
            "org.gnome.Shell", "/org/gnome/Shell/Extensions/CodexQuota",
            "org.gnome.Shell.Extensions.CodexQuota", "Update", "s", (payload,), timeout=2,
        )
    except dbus.DBusException:
        pass


def main():
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    bus = dbus.SessionBus()
    publish(bus, None)
    retry_until = time.monotonic() + 60
    try:
        while not stop.is_set():
            started = time.monotonic()
            interval = 2 if started < retry_until else 60
            remaining = read_weekly(stop, timeout=2 if interval == 2 else 10)
            if stop.is_set():
                break
            if remaining is not None:
                retry_until = 0
                interval = 60
            publish(bus, remaining)
            stop.wait(max(0, interval - (time.monotonic() - started)))
    finally:
        publish(bus, None)


if __name__ == "__main__":
    main()
