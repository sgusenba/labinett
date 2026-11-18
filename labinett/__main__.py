"""Startpunkt: ``python -m labinett`` bzw. labinett.exe."""

from __future__ import annotations

import os

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")

import socket  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import webbrowser  # noqa: E402

import uvicorn  # noqa: E402

from . import config  # noqa: E402
from .app import erstelle_app  # noqa: E402


def main() -> None:
    einst = config.laden()
    app = erstelle_app(einst)
    url = f"http://127.0.0.1:{einst.port}/"
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", einst.port)) == 0:
            print(f"Port {einst.port} ist belegt – läuft labinett schon? Öffne {url}")
            webbrowser.open(url)
            sys.exit(1)
    print(f"labinett läuft auf {url}  (Beenden mit Strg+C)")
    print(f"CSV: {einst.csv_datei()}")
    if einst.browser_oeffnen:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=einst.port, log_level="warning")


if __name__ == "__main__":
    main()
