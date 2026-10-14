"""Immutable ciphertext storage over a chosen folder or WebDAV collection."""
from __future__ import annotations

import base64
import os
from pathlib import Path
import secrets
from urllib.error import HTTPError
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree

from vault_unified.personal_sync.codec import MAX_RECORD_BYTES, ProtocolError, identifier, record_identity

MAX_RECORDS = 100_000
MAX_LIST_BYTES = 32 * 1024 * 1024


class StorageUnavailable(ValueError):
    pass


def _record_names(names):
    result = []
    for name in names:
        try:
            record_identity(name)
        except ProtocolError:
            continue  # Ignore temporary files and unrelated user-owned files.
        result.append(name)
        if len(result) > MAX_RECORDS:
            raise StorageUnavailable("Synchronization storage contains too many records")
    return sorted(set(result))


class FolderStore:
    def __init__(self, directory: str | Path, space: str, *, create: bool = False):
        self.root = Path(directory).expanduser().resolve() / ("VaultUnified-" + identifier(space))
        if create:
            self.root.mkdir(parents=False, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise StorageUnavailable("Synchronization folder is unavailable")

    def list(self) -> list[str]:
        try:
            return _record_names(item.name for item in self.root.iterdir() if item.is_file() and not item.is_symlink())
        except OSError:
            raise StorageUnavailable("Synchronization folder could not be read") from None

    def get(self, name: str) -> bytes:
        record_identity(name)
        path = self.root / name
        try:
            if path.is_symlink() or not path.is_file():
                raise OSError()
            with path.open("rb") as stream:
                data = stream.read(MAX_RECORD_BYTES + 1)
            if len(data) > MAX_RECORD_BYTES:
                raise OSError()
            return data
        except OSError:
            raise StorageUnavailable("Synchronized change is unavailable") from None

    def put(self, name: str, encrypted: bytes) -> None:
        record_identity(name)
        if not isinstance(encrypted, bytes) or len(encrypted) > MAX_RECORD_BYTES:
            raise StorageUnavailable("Synchronized change exceeds its limit")
        destination = self.root / name
        if destination.exists():
            if self.get(name) != encrypted:
                raise StorageUnavailable("A different change already uses this device sequence")
            return
        temporary = self.root / (".upload-" + secrets.token_hex(16))
        try:
            with temporary.open("xb") as stream:
                stream.write(encrypted); stream.flush(); os.fsync(stream.fileno())
            try:
                # Windows rename is atomic and refuses an existing destination.
                # POSIX rename replaces; a hard link supplies no-replace there.
                if os.name == "nt": os.rename(temporary, destination)
                else: os.link(temporary, destination)
            except FileExistsError:
                if self.get(name) != encrypted:
                    raise StorageUnavailable("A different change already uses this device sequence") from None
        except OSError:
            raise StorageUnavailable("Synchronized change could not be saved") from None
        finally:
            temporary.unlink(missing_ok=True)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class WebDAVStore:
    def __init__(self, address: str, space: str, username: str, password: str, *, create: bool = False):
        parsed = urlsplit(address)
        local = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
        if (parsed.scheme != "https" and not (parsed.scheme == "http" and local)) or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
            raise StorageUnavailable("Use an HTTPS WebDAV folder address without embedded credentials")
        try:
            parsed.port
            if any(char in address for char in "\r\n\t\\") or ":" in username or any(char in username + password for char in "\r\n"):
                raise ValueError()
        except ValueError:
            raise StorageUnavailable("Invalid WebDAV connection settings") from None
        self.base = urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") + "/VaultUnified-" + identifier(space) + "/", "", ""))
        self.authorization = "Basic " + base64.b64encode((username + ":" + password).encode("utf-8")).decode("ascii")
        self.opener = build_opener(_NoRedirect())
        if create:
            self._request("MKCOL", "", allowed={201, 405})

    def _request(self, method, name, *, data=None, headers=None, allowed=None, limit=MAX_RECORD_BYTES):
        if name:
            record_identity(name)
        request = Request(self.base + quote(name), data=data, method=method,
                          headers={"Authorization": self.authorization, "User-Agent": "Vault-Unified", "Accept-Encoding": "identity", **(headers or {})})
        try:
            try:
                response = self.opener.open(request, timeout=15)
            except HTTPError as error:
                response = error
            with response:
                if response.code not in (allowed or {200}):
                    raise ValueError()
                body = response.read(limit + 1)
                if len(body) > limit:
                    raise ValueError()
                return response.code, body
        except Exception:
            raise StorageUnavailable("WebDAV request failed; check the connection and retry") from None

    def list(self) -> list[str]:
        _, body = self._request("PROPFIND", "", data=b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>',
                                headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"}, allowed={207}, limit=MAX_LIST_BYTES)
        try:
            if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
                raise ValueError()
            root = ElementTree.fromstring(body)
            if root.tag != "{DAV:}multistatus":
                raise ValueError()
            base = urlsplit(self.base)
            names = []
            for response in root.findall("{DAV:}response"):
                href = response.findtext("{DAV:}href", "")
                parsed = urlsplit(href)
                if parsed.netloc and (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
                    raise ValueError()
                path = unquote(parsed.path)
                prefix = unquote(base.path)
                if path == prefix or path == prefix.rstrip("/"):
                    continue
                if not path.startswith(prefix):
                    raise ValueError()
                name = path[len(prefix):]
                if "/" in name or "\\" in name:
                    continue
                names.append(name)
            return _record_names(names)
        except Exception:
            raise StorageUnavailable("WebDAV returned an invalid folder listing") from None

    def get(self, name: str) -> bytes:
        return self._request("GET", name)[1]

    def put(self, name: str, encrypted: bytes) -> None:
        if not isinstance(encrypted, bytes) or len(encrypted) > MAX_RECORD_BYTES:
            raise StorageUnavailable("Synchronized change exceeds its limit")
        status, existing = self._request("GET", name, allowed={200, 404})
        if status == 200:
            if existing != encrypted:
                raise StorageUnavailable("A different change already uses this device sequence")
            return
        self._request("PUT", name, data=encrypted, headers={"Content-Type": "application/octet-stream", "If-None-Match": "*"}, allowed={201, 204, 412})
        # Conditional creation protects races on compliant WebDAV servers.
        # Read-back also catches partial or discarded successful uploads.
        if self.get(name) != encrypted:
            raise StorageUnavailable("WebDAV did not preserve the immutable change")
