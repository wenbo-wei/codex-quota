#!/usr/bin/python3
"""Install or uninstall Codex Quota for the current desktop user."""

import argparse
import ast
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
USER_DIR = Path.home()
UUID = "codex-quota@wenbo-wei"
UNIT = "codex-quota.service"


def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True, timeout=15).stdout.strip()


def registration_files():
    extension = USER_DIR / ".local/share/gnome-shell/extensions" / UUID
    source = ROOT / "extensions" / UUID
    service = """[Unit]
Description=Codex weekly quota
PartOf=graphical-session.target
After=graphical-session.target

[Service]
ExecStart=/usr/bin/python3 -I %h/Applications/codex-quota/quota.py
Restart=on-failure
RestartSec=2
TimeoutStopSec=5
NoNewPrivileges=yes
PrivateTmp=yes
UMask=0077
"""
    return {
        USER_DIR / ".config/systemd/user" / UNIT: service,
        USER_DIR / ".config/systemd/user/graphical-session.target.d/codex-quota.conf": "[Unit]\nWants=codex-quota.service\n",
        extension / "metadata.json": (source / "metadata.json").read_text(),
        extension / "extension.js": f"export {{default}} from {json.dumps((source / 'extension.js').as_uri())};\n",
        extension / "stylesheet.css": f"@import url({json.dumps((source / 'stylesheet.css').as_uri())});\n",
    }


def write_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), 0o644)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uninstall", action="store_true")
    uninstall = parser.parse_args().uninstall
    if ROOT != USER_DIR / "Applications/codex-quota":
        raise SystemExit("Place the project in ~/Applications/codex-quota.")
    files = registration_files()
    if any(path.is_symlink() or (path.exists() and not path.is_file()) for path in files):
        raise SystemExit("Registration paths must be regular files.")
    enabled = ast.literal_eval(run("gsettings", "get", "org.gnome.shell", "enabled-extensions").removeprefix("@as "))
    if uninstall:
        run("gsettings", "set", "org.gnome.shell", "enabled-extensions", repr([x for x in enabled if x != UUID]))
        run("systemctl", "--user", "stop", UNIT)
        for path in files:
            path.unlink(missing_ok=True)
    else:
        for path, content in files.items():
            write_file(path, content)
        if UUID not in enabled:
            run("gsettings", "set", "org.gnome.shell", "enabled-extensions", repr([*enabled, UUID]))
    run("systemctl", "--user", "daemon-reload")
    print("Uninstalled." if uninstall else "Installed. Log out and log in to start.")


if __name__ == "__main__":
    main()
