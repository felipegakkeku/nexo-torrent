from __future__ import annotations

import argparse
import ctypes
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import uvicorn

from api import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("nexo.torrent.main")


def _start_parent_watchdog(parent_pid: int, on_parent_dead) -> None:
    if parent_pid <= 0 or sys.platform != "win32":
        return

    SYNCHRONIZE = 0x00100000
    WAIT_OBJECT_0 = 0x00000000

    def _watch() -> None:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(parent_pid))
        if not handle:
            logger.warning("Processo pai %s não acessível; encerrando engine.", parent_pid)
            on_parent_dead()
            return
        try:
            while True:
                res = kernel32.WaitForSingleObject(handle, 1000)
                if res == WAIT_OBJECT_0:
                    logger.info("Processo pai %s encerrou; finalizando engine.", parent_pid)
                    on_parent_dead()
                    return
                if os.getppid() == 1:
                    on_parent_dead()
                    return
        finally:
            kernel32.CloseHandle(handle)

    t = threading.Thread(target=_watch, name="parent-watchdog", daemon=True)
    t.start()


def main() -> None:
    parser = argparse.ArgumentParser(description="Nexo Torrent Engine")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=19742)
    parser.add_argument("--token", default="")
    parser.add_argument("--parent-pid", type=int, default=0)
    args = parser.parse_args()

    server_ref: dict[str, uvicorn.Server | None] = {"server": None}

    def _request_exit() -> None:
        srv = server_ref.get("server")
        if srv is not None:
            srv.should_exit = True

    app = create_app(api_token=args.token, on_shutdown_request=_request_exit)
    config = uvicorn.Config(
        app,
        host=args.host,
        port=args.port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server_ref["server"] = server

    def _handle_signal(_sig, _frame):
        _request_exit()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    _start_parent_watchdog(args.parent_pid, _request_exit)
    logger.info("Nexo Torrent Engine ouvindo em http://%s:%d", args.host, args.port)
    server.run()


if __name__ == "__main__":
    main()
