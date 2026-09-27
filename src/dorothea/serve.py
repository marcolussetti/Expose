"""Local preview server for ``dorothea serve`` (#6).

Navigation links point at directories (``../nature/mountains``), which only work where a server
answers with the directory's ``index.html``; opened from disk (``file://``) they show a folder
listing. This serves ``_site`` with the standard library, adding what a preview needs on top of
``SimpleHTTPRequestHandler``: byte ranges (Safari/iOS won't play a video without them, and other
browsers can't seek) and ``Cache-Control: no-cache`` so a rebuilt page is picked up on reload.
"""

import os
import re
import shutil
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import BinaryIO

_RANGE = re.compile(r"bytes=(\d*)-(\d*)")


class PreviewHandler(SimpleHTTPRequestHandler):
    """Static files with single byte-range support and quiet logging (errors only)."""

    _range: tuple[int, int] | None = None

    def end_headers(self) -> None:
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def send_head(self) -> BinaryIO | None:
        self._range = None
        header = self.headers.get("Range")
        path = self.translate_path(self.path)
        if not header or os.path.isdir(path):
            return super().send_head()
        match = _RANGE.fullmatch(header.strip())
        if not match or match.groups() == ("", ""):
            return super().send_head()
        try:
            f = open(path, "rb")  # noqa: SIM115 - returned to the caller, which closes it
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return None
        size = os.fstat(f.fileno()).st_size
        first, last = match.groups()
        if first:
            start, end = int(first), min(int(last), size - 1) if last else size - 1
        else:  # "bytes=-N": the last N bytes
            start, end = max(size - int(last), 0), size - 1
        if start >= size or start > end:
            f.close()
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        self.send_response(HTTPStatus.PARTIAL_CONTENT)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Last-Modified", self.date_time_string(int(os.fstat(f.fileno()).st_mtime)))
        self.end_headers()
        self._range = (start, end)
        return f

    def copyfile(self, source: BinaryIO, outputfile: BinaryIO) -> None:  # ty: ignore[invalid-method-override]
        if self._range is None:
            shutil.copyfileobj(source, outputfile)
            return
        start, end = self._range
        source.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = source.read(min(remaining, 64 * 1024))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        if isinstance(code, HTTPStatus):
            code = code.value
        if isinstance(code, int) and code >= 400:
            super().log_request(code, size)


def make_server(site: Path, bind: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    """A server for ``site`` (port 0 picks a free port). Raises OSError if the port is taken."""
    handler = partial(PreviewHandler, directory=str(site))
    return ThreadingHTTPServer((bind, port), handler)


def run(server: ThreadingHTTPServer, site: Path) -> None:
    """Serve until Ctrl-C, then close the server."""
    with server:
        host, port = server.server_address[:2]
        shown = "localhost" if host == "127.0.0.1" else host
        print(f"Serving {site} at http://{shown}:{port}/ (Ctrl-C to stop)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print()
