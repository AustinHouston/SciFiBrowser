from __future__ import annotations

import json
import signal
import threading
import webbrowser
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .launcher import (
    init_catalog,
    register_data,
    start_registration_watcher,
    start_server,
    wait_for_server,
    write_runtime_config,
)
from .settings import (
    DEFAULT_API_KEY,
    DEFAULT_CATALOG,
    DEFAULT_DATA_ROOT,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_RUNTIME_CONFIG,
)


LAUNCHER_HOST = "127.0.0.1"
LAUNCHER_PORT = 8765


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SciFiBrowser Launcher</title>
  <style>
    :root {
      color-scheme: light;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f6f7f9;
      color: #1f252d;
    }
    body { margin: 0; }
    main {
      max-width: 760px;
      margin: 48px auto;
      padding: 0 24px;
    }
    h1 {
      margin: 0 0 24px;
      font-size: 32px;
      font-weight: 700;
      letter-spacing: 0;
    }
    .panel {
      background: white;
      border: 1px solid #dde1e7;
      border-radius: 8px;
      padding: 24px;
      box-shadow: 0 8px 24px rgba(22, 30, 42, 0.08);
    }
    label {
      display: block;
      font-size: 14px;
      font-weight: 650;
      margin-bottom: 8px;
    }
    input, select {
      box-sizing: border-box;
      width: 100%;
      height: 42px;
      border: 1px solid #cbd2dc;
      border-radius: 6px;
      padding: 0 12px;
      font-size: 15px;
      background: white;
      color: #1f252d;
      margin-bottom: 18px;
    }
    .actions {
      display: flex;
      gap: 10px;
      margin-top: 6px;
    }
    button {
      height: 42px;
      border: 0;
      border-radius: 6px;
      padding: 0 18px;
      font-size: 15px;
      font-weight: 700;
      cursor: pointer;
    }
    #run { background: #315fdc; color: white; }
    #stop { background: #e9edf4; color: #1f252d; }
    #open { background: #eef5ef; color: #195d2d; }
    button:disabled { opacity: 0.55; cursor: not-allowed; }
    #loading {
      display: none;
      margin-top: 22px;
      padding: 16px;
      border-radius: 8px;
      background: #f8fafc;
      border: 1px solid #dde5ef;
    }
    .bar {
      height: 10px;
      overflow: hidden;
      border-radius: 999px;
      background: #dfe6f2;
      margin: 12px 0;
    }
    .bar::before {
      content: "";
      display: block;
      height: 100%;
      width: 35%;
      border-radius: 999px;
      background: #315fdc;
      animation: slide 1.2s infinite ease-in-out;
    }
    @keyframes slide {
      0% { transform: translateX(-110%); }
      100% { transform: translateX(310%); }
    }
    #status {
      min-height: 22px;
      font-size: 14px;
      color: #4a5565;
      word-break: break-word;
    }
    #url {
      margin-top: 12px;
      font-size: 14px;
    }
  </style>
</head>
<body>
  <main>
    <h1>SciFiBrowser Launcher</h1>
    <section class="panel">
      <label for="host">IP address</label>
      <input id="host" value="127.0.0.1" spellcheck="false">

      <label for="folder">Data folder</label>
      <select id="folder"></select>

      <div class="actions">
        <button id="run">Run</button>
        <button id="stop" type="button">Stop</button>
        <button id="open" type="button" disabled>Open Tiled</button>
      </div>

      <div id="loading">
        <strong>Indexing selected folder...</strong>
        <div class="bar"></div>
        <div id="status">Ready</div>
        <div id="url"></div>
      </div>
    </section>
  </main>
  <script>
    const host = document.querySelector("#host");
    const folder = document.querySelector("#folder");
    const run = document.querySelector("#run");
    const stop = document.querySelector("#stop");
    const openButton = document.querySelector("#open");
    const loading = document.querySelector("#loading");
    const status = document.querySelector("#status");
    const url = document.querySelector("#url");
    let currentUrl = "";

    async function loadFolders() {
      const response = await fetch("/api/folders");
      const folders = await response.json();
      folder.innerHTML = "";
      for (const item of folders) {
        const option = document.createElement("option");
        option.value = item.path;
        option.textContent = item.label;
        folder.appendChild(option);
      }
    }

    async function refreshStatus() {
      const response = await fetch("/api/status");
      const state = await response.json();
      status.textContent = state.message;
      loading.style.display = state.started ? "block" : "none";
      run.disabled = state.busy;
      openButton.disabled = !state.ui_url;
      currentUrl = state.ui_url || "";
      url.textContent = currentUrl ? currentUrl : "";
      if (state.error) {
        loading.style.display = "block";
      }
    }

    run.addEventListener("click", async () => {
      loading.style.display = "block";
      status.textContent = "Starting...";
      run.disabled = true;
      await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ host: host.value, folder: folder.value })
      });
      refreshStatus();
    });

    stop.addEventListener("click", async () => {
      await fetch("/api/stop", { method: "POST" });
      refreshStatus();
    });

    openButton.addEventListener("click", () => {
      if (currentUrl) window.open(currentUrl, "_blank");
    });

    loadFolders();
    refreshStatus();
    setInterval(refreshStatus, 1000);
  </script>
</body>
</html>
"""


class LauncherState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.server = None
        self.watcher = None
        self.started = False
        self.busy = False
        self.message = "Ready"
        self.error = ""
        self.ui_url = ""

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            return {
                "started": self.started,
                "busy": self.busy,
                "message": self.message,
                "error": self.error,
                "ui_url": self.ui_url,
            }

    def update(self, **kwargs: object) -> None:
        with self.lock:
            for key, value in kwargs.items():
                setattr(self, key, value)

    def stop_processes(self) -> None:
        with self.lock:
            processes = (self.watcher, self.server)
            self.watcher = None
            self.server = None
            self.started = False
            self.busy = False
            self.ui_url = ""
            self.message = "Stopped"
        for process in processes:
            if process and process.poll() is None:
                process.terminate()


STATE = LauncherState()


def folder_choices() -> list[dict[str, str]]:
    choices = [{"label": str(DEFAULT_DATA_ROOT), "path": str(DEFAULT_DATA_ROOT)}]
    if DEFAULT_DATA_ROOT.exists():
        for path in sorted(DEFAULT_DATA_ROOT.iterdir()):
            if path.is_dir():
                choices.append({"label": path.name, "path": str(path)})
    return choices


def run_scifibrowser(host: str, data_root: Path) -> None:
    base_url = f"http://{host}:{DEFAULT_PORT}"
    ui_url = f"{base_url}/ui/"
    try:
        STATE.update(started=True, busy=True, error="", ui_url="", message="Preparing catalog...")
        init_catalog(DEFAULT_CATALOG)
        write_runtime_config(DEFAULT_RUNTIME_CONFIG, DEFAULT_CATALOG, data_root)

        STATE.update(message="Starting Tiled server...")
        server = start_server(host, DEFAULT_PORT, DEFAULT_API_KEY, DEFAULT_RUNTIME_CONFIG)
        STATE.update(server=server)
        wait_for_server(base_url)

        STATE.update(message="Indexing files. This can take a while for large folders...")
        register_data(base_url, data_root, DEFAULT_API_KEY, verbose=False)

        watcher = start_registration_watcher(
            base_url,
            data_root,
            DEFAULT_API_KEY,
            interval=300,
            verbose=False,
        )
        STATE.update(
            watcher=watcher,
            busy=False,
            ui_url=ui_url,
            message=f"Ready. Tiled is running at {ui_url}",
        )
        webbrowser.open(ui_url)
    except Exception as exc:
        STATE.stop_processes()
        STATE.update(started=True, error=str(exc), message=f"Error: {exc}")


class LauncherHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_text(HTML, "text/html; charset=utf-8")
        elif parsed.path == "/api/folders":
            self._send_json(folder_choices())
        elif parsed.path == "/api/status":
            self._send_json(STATE.snapshot())
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/run":
            payload = self._read_json()
            host = str(payload.get("host") or DEFAULT_HOST).strip() or DEFAULT_HOST
            data_root = Path(str(payload.get("folder") or DEFAULT_DATA_ROOT)).expanduser().resolve()
            if not data_root.exists():
                self._send_json({"ok": False, "error": f"Folder not found: {data_root}"}, status=400)
                return
            if STATE.snapshot()["busy"]:
                self._send_json({"ok": False, "error": "SciFiBrowser is already starting."}, status=409)
                return
            STATE.stop_processes()
            threading.Thread(target=run_scifibrowser, args=(host, data_root), daemon=True).start()
            self._send_json({"ok": True})
        elif parsed.path == "/api/stop":
            STATE.stop_processes()
            self._send_json({"ok": True})
        else:
            self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("content-length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _send_json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, payload: str, content_type: str) -> None:
        body = payload.encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open the SciFiBrowser web launcher.")
    parser.add_argument("--host", default=LAUNCHER_HOST)
    parser.add_argument("--port", type=int, default=LAUNCHER_PORT)
    parser.add_argument("--no-open", action="store_true", help="Do not open the launcher in a browser.")
    args = parser.parse_args(argv)

    server = ThreadingHTTPServer((args.host, args.port), LauncherHandler)
    url = f"http://{args.host}:{args.port}/"

    def shutdown(*_: object) -> None:
        STATE.stop_processes()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    print(f"SciFiBrowser launcher: {url}")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    finally:
        STATE.stop_processes()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
