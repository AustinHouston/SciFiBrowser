from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from .settings import (
    DEFAULT_API_KEY,
    DEFAULT_CATALOG,
    DEFAULT_RUNTIME_CONFIG,
    DEFAULT_DATA_ROOT,
    DEFAULT_HOST,
    DEFAULT_PORT,
    PROJECT_ROOT,
    PYTEMLIB_EXTENSIONS,
    PYTEMLIB_MIMETYPE,
)


def _tiled_executable() -> str:
    candidate = Path(sys.executable).with_name("tiled")
    if candidate.exists():
        return str(candidate)
    return "tiled"


def _environment() -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    paths = [str(PROJECT_ROOT)]
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def _run(command: list[str]) -> None:
    subprocess.run(command, cwd=PROJECT_ROOT, env=_environment(), check=True)


def _sqlite_uri(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.expanduser().resolve()}"


def write_runtime_config(config: Path, catalog: Path, data_root: Path) -> None:
    config.write_text(
        "\n".join(
            [
                "trees:",
                "  - path: /",
                "    tree: tiled.catalog:from_uri",
                "    args:",
                f"      uri: {_sqlite_uri(catalog)}",
                "      readable_storage:",
                f"        - {data_root}",
                "      adapters_by_mimetype:",
                "        application/x-pytemlib: custom:PyTEMlibAdapter",
                "        application/x-emd: custom:PyTEMlibAdapter",
                "",
            ]
        ),
        encoding="utf-8",
    )


def init_catalog(catalog: Path) -> None:
    catalog.parent.mkdir(parents=True, exist_ok=True)
    if catalog.exists():
        _run([_tiled_executable(), "catalog", "upgrade-database", str(catalog)])
        return

    _run([_tiled_executable(), "catalog", "init", "--if-not-exists", str(catalog)])


def start_server(host: str, port: int, api_key: str, config: Path) -> subprocess.Popen:
    command = [
        _tiled_executable(),
        "serve",
        "config",
        "--public",
        str(config),
        "--api-key",
        api_key,
        "--host",
        host,
        "--port",
        str(port),
    ]
    return subprocess.Popen(command, cwd=PROJECT_ROOT, env=_environment())


def wait_for_server(base_url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(base_url, timeout=1):
                return
        except URLError:
            time.sleep(0.25)
    raise TimeoutError(f"Tiled did not respond at {base_url} within {timeout:.0f}s")


def register_data(
    base_url: str,
    data_root: Path,
    api_key: str,
    *,
    verbose: bool,
) -> None:
    command = [
        _tiled_executable(),
        "register",
        base_url,
        str(data_root),
        "--api-key",
        api_key,
        "--adapter",
        f"{PYTEMLIB_MIMETYPE}=custom:PyTEMlibAdapter",
        "--keep-ext",
    ]

    for extension in PYTEMLIB_EXTENSIONS:
        command.extend(["--ext", f"{extension}={PYTEMLIB_MIMETYPE}"])
        command.extend(["--include-ext", extension])

    if verbose:
        command.append("--verbose")

    _run(command)


def start_registration_watcher(
    base_url: str,
    data_root: Path,
    api_key: str,
    *,
    interval: int,
    verbose: bool,
) -> subprocess.Popen:
    command = [
        sys.executable,
        "-m",
        "scifibrowser.launcher",
        "register",
        base_url,
        "--data-root",
        str(data_root),
        "--api-key",
        api_key,
        "--watch",
        "--watch-interval",
        str(interval),
    ]
    if verbose:
        command.append("--verbose")
    return subprocess.Popen(command, cwd=PROJECT_ROOT, env=_environment())


def register_forever(
    base_url: str,
    data_root: Path,
    api_key: str,
    *,
    interval: int,
    verbose: bool,
) -> int:
    while True:
        started = time.monotonic()
        try:
            register_data(base_url, data_root, api_key, verbose=verbose)
            print(f"SciFiBrowser registration refresh complete. Next refresh in {interval}s.", flush=True)
        except subprocess.CalledProcessError as exc:
            print(
                f"SciFiBrowser registration refresh failed with exit code {exc.returncode}; "
                f"keeping the GUI alive and retrying in {interval}s.",
                file=sys.stderr,
                flush=True,
            )

        elapsed = time.monotonic() - started
        time.sleep(max(1, interval - int(elapsed)))


def serve(args: argparse.Namespace) -> int:
    data_root = args.data_root.expanduser().resolve()
    if not data_root.exists():
        raise FileNotFoundError(f"Data root does not exist: {data_root}")

    catalog = args.catalog.expanduser().resolve()
    config = args.config.expanduser().resolve()

    init_catalog(catalog)
    if args.write_config:
        write_runtime_config(config, catalog, data_root)

    base_url = f"http://{args.host}:{args.port}"
    ui_url = f"{base_url}/ui/"
    server = start_server(args.host, args.port, args.api_key, config)
    watcher: subprocess.Popen | None = None

    def shutdown(*_: object) -> None:
        for process in (watcher, server):
            if process and process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        wait_for_server(base_url)
        if args.register:
            if args.watch:
                watcher = start_registration_watcher(
                    base_url,
                    data_root,
                    args.api_key,
                    interval=args.watch_interval,
                    verbose=args.verbose,
                )
            else:
                register_data(base_url, data_root, args.api_key, verbose=args.verbose)

        print()
        print("SciFiBrowser is running.")
        print(f"Tiled UI: {ui_url}")
        print(f"Python client URI: {base_url}")
        print(f"Data root: {data_root}")
        print("Press Ctrl+C to stop.")
        print()

        while server.poll() is None:
            if watcher and watcher.poll() is not None:
                return watcher.returncode or 1
            time.sleep(0.5)
        return server.returncode or 0
    finally:
        shutdown()


def register(args: argparse.Namespace) -> int:
    data_root = args.data_root.expanduser().resolve()
    if args.watch:
        return register_forever(
            args.server,
            data_root,
            args.api_key,
            interval=args.watch_interval,
            verbose=args.verbose,
        )

    register_data(args.server, data_root, args.api_key, verbose=args.verbose)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scifibrowser",
        description="Run a local Tiled GUI for pyTEMlib-readable scientific files.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    gui_parser = subparsers.add_parser("gui", help="Open the simple desktop launcher.")
    gui_parser.set_defaults(func=gui)

    serve_parser = subparsers.add_parser("serve", help="Start Tiled and print the local GUI URL.")
    serve_parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    serve_parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    serve_parser.add_argument("--config", type=Path, default=DEFAULT_RUNTIME_CONFIG)
    serve_parser.add_argument(
        "--write-config",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write a runtime Tiled config for the selected data root and catalog.",
    )
    serve_parser.add_argument("--host", default=DEFAULT_HOST)
    serve_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve_parser.add_argument("--api-key", default=DEFAULT_API_KEY)
    serve_parser.add_argument("--register", action="store_true", help="Register data after the server starts.")
    serve_parser.add_argument(
        "--watch",
        action="store_true",
        help="Keep registration refreshed without using Tiled's fragile built-in watcher.",
    )
    serve_parser.add_argument("--watch-interval", type=int, default=300)
    serve_parser.add_argument("--verbose", action="store_true", help="Show Tiled registration details.")
    serve_parser.set_defaults(func=serve)

    register_parser = subparsers.add_parser("register", help="Register files into an already-running Tiled server.")
    register_parser.add_argument("server", nargs="?", default=f"http://{DEFAULT_HOST}:{DEFAULT_PORT}")
    register_parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    register_parser.add_argument("--api-key", default=DEFAULT_API_KEY)
    register_parser.add_argument("--watch", action="store_true")
    register_parser.add_argument("--watch-interval", type=int, default=300)
    register_parser.add_argument("--verbose", action="store_true")
    register_parser.set_defaults(func=register)

    return parser


def gui(args: argparse.Namespace) -> int:
    from .desktop_launcher import main as gui_main

    return gui_main()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
