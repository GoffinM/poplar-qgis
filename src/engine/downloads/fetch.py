"""Downloading files into a local cache, with progress and cancellation."""

from __future__ import annotations

import os
import shutil
import urllib.error
import urllib.request
from typing import Callable, Optional

Progress = Callable[[int, Optional[int]], None]
"""Called with (bytes received, total bytes or None)."""
Cancelled = Callable[[], bool]

CHUNK = 1 << 20


class DownloadCancelled(Exception):
    """The user stopped the download."""


class RemoteMissing(Exception):
    """The server has no such file (HTTP 404): for tiled datasets, a tile without buildings."""


class IncompleteDownload(IOError):
    """The server closed the connection before the end of the file."""


class UrllibFetcher:
    """Plain Python download, streamed to disk.

    Without ``proxy``, the proxy of the system or the environment is used (as
    browsers do); the plugin passes the proxy set in the QGIS options, if any.
    """

    def __init__(self, timeout: float = 60.0, proxy: Optional[str] = None):
        self.timeout = timeout
        self.proxy = proxy
        handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy})] if proxy else []
        self._opener = urllib.request.build_opener(*handlers)

    def text(self, url: str) -> str:
        """A small text document (a listing), read at once."""
        with self._opener.open(url, timeout=self.timeout) as response:
            return response.read().decode("utf-8")

    def size(self, url: str) -> Optional[int]:
        request = urllib.request.Request(url, method="HEAD")
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                length = response.headers.get("Content-Length")
                return int(length) if length else None
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise RemoteMissing(url) from error
            raise

    def fetch(self, url: str, path: str, progress: Optional[Progress] = None,
              cancelled: Optional[Cancelled] = None) -> None:
        try:
            response = self._opener.open(url, timeout=self.timeout)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise RemoteMissing(url) from error
            raise
        with response, open(path, "wb") as handle:
            length = response.headers.get("Content-Length")
            total = int(length) if length else None
            received = 0
            while True:
                if cancelled is not None and cancelled():
                    raise DownloadCancelled(url)
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                handle.write(chunk)
                received += len(chunk)
                if progress is not None:
                    progress(received, total)
        if total is not None and received != total:        # connection closed early: never cached
            raise IncompleteDownload(f"{url}: {received} bytes received out of {total}")


class FileCache:
    """Files kept under ``folder/<key>``; a file is downloaded only once.

    Downloads go to a ``.part`` file renamed at the end, so an interrupted
    download never leaves a truncated file in the cache.
    """

    def __init__(self, folder: str, fetcher=None):
        self.folder = folder
        self.fetcher = fetcher or UrllibFetcher()

    def path(self, key: str) -> str:
        return os.path.join(self.folder, *key.split("/"))

    def has(self, key: str) -> bool:
        return os.path.isfile(self.path(key))

    def get(self, key: str, url: str, progress: Optional[Progress] = None,
            cancelled: Optional[Cancelled] = None) -> str:
        path = self.path(key)
        if os.path.isfile(path):
            return path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        part = path + ".part"
        try:
            self.fetcher.fetch(url, part, progress, cancelled)
        except BaseException:
            if os.path.exists(part):
                os.remove(part)
            raise
        shutil.move(part, path)
        return path
