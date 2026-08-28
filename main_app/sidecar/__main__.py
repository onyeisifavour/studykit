"""
sidecar/__main__.py

Entry point for the StudyKit sidecar. Binds 127.0.0.1 on an ephemeral port
(unless STUDYKIT_PORT is set) and prints `STUDYKIT_PORT=<port>` to stdout so
the Electron main process can discover it.

Run directly:
    python -m main_app.sidecar
"""

import os
import socket
import sys

import uvicorn

from .app import app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main() -> None:
    port = int(os.environ.get('STUDYKIT_PORT') or _free_port())
    print(f'STUDYKIT_PORT={port}', flush=True)
    uvicorn.run(
        app,
        host='127.0.0.1',
        port=port,
        log_level='warning',
        access_log=False,
    )


if __name__ == '__main__':
    sys.exit(main())
