"""Folder-backed storage. File contents are streamed; paths never leave the host."""
import base64
import mimetypes
import os
import shutil
import stat
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException
from .config import CHUNK, FOLDER, valid_name


def safe_name(name):
    name = valid_name(name)
    if (any(c in name for c in ':*?"<>|') or name.endswith(('.', ' '))
            or name.lower().startswith('.locin-upload-')
            or name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *('COM'+str(n) for n in range(10)), *('LPT'+str(n) for n in range(10))}):
        raise ValueError('Choose a normal filename without reserved characters or device names.')
    return name


def check_path(path):
    for part in [*reversed(path.parents), path]:
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Linked folders and files cannot be shared. Choose a regular local folder.')
    if path.is_file() and path.stat().st_nlink > 1:
        raise ValueError('Hard-linked files cannot be shared.')
    return path


def validate_folder(value):
    path = Path(value)
    try:
        if not value or not path.is_absolute() or '..' in path.parts or path == Path(path.anchor):
            raise ValueError('Choose an existing folder on this computer, not an entire drive.')
        check_path(path)
        if not path.is_dir():
            raise ValueError('Choose an existing folder on this computer.')
    except OSError:
        raise ValueError('This folder is unavailable. Check its location and permissions.') from None
    return str(path)


class LocalDownload:
    def __init__(self, path):
        self.stream = path.open('rb')
        self.headers = {'content-length': str(os.fstat(self.stream.fileno()).st_size)}

    def iter_bytes(self, chunk_size):
        while True:
            data = self.stream.read(chunk_size)
            if not data:
                break
            yield data

    def close(self):
        self.stream.close()


class LocalStorage:
    def __init__(self, db):
        self.db = db
        self.sessions = {}
        self.lock = threading.RLock()

    def root(self):
        return Path(validate_folder(self.db.settings()['local_folder'])).resolve()

    def identifier(self, path):
        relative = path.relative_to(self.root()).as_posix()
        return 'local_root' if relative == '.' else 'local_' + base64.urlsafe_b64encode(relative.encode()).decode().rstrip('=')

    def path(self, identifier):
        root = self.root()
        if identifier == 'local_root':
            return root
        try:
            if not identifier.startswith('local_') or len(identifier) > 8192:
                raise ValueError()
            encoded = identifier[6:]
            relative = base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True).decode()
            parts = relative.split('/')
            if not parts or any(safe_name(part) != part for part in parts):
                raise ValueError()
            path = root.joinpath(*parts)
            check_path(path)
            path.resolve().relative_to(root.resolve())
            return path.resolve()
        except (ValueError, UnicodeError, OSError):
            raise HTTPException(404, 'File or folder is unavailable.') from None

    def metadata(self, identifier):
        path = self.path(identifier)
        info = path.stat()
        if not stat.S_ISDIR(info.st_mode) and not stat.S_ISREG(info.st_mode):
            raise HTTPException(404, 'File is unavailable.')
        return {'id': self.identifier(path), 'name': path.name, 'mimeType': FOLDER if path.is_dir() else mimetypes.guess_type(path.name)[0] or 'application/octet-stream',
                'size': str(info.st_size) if path.is_file() else None,
                'parents': [] if identifier == 'local_root' else [self.identifier(path.parent)],
                'modifiedTime': datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat()}

    def contained(self, identifier, root, folder=False):
        if root != 'local_root':
            raise HTTPException(404, 'Shared folder is unavailable.')
        result = self.metadata(identifier)
        if folder and result['mimeType'] != FOLDER:
            raise HTTPException(400, 'Choose a folder.')
        return result

    def listing(self, parent, page=None, search='', folders_only=False):
        with self.lock:
            path = self.path(parent)
            try:
                offset = int(page or 0)
                if offset < 0:
                    raise ValueError()
            except ValueError:
                raise HTTPException(400, 'Invalid page.') from None
            files = []
            for child in path.iterdir():
                if child.name.lower().startswith('.locin-upload-') or search.casefold() not in child.name.casefold():
                    continue
                try:
                    item = self.metadata(self.identifier(child))
                except (ValueError, HTTPException, OSError):
                    continue
                if not folders_only or item['mimeType'] == FOLDER:
                    files.append(item)
            files.sort(key=lambda item: (item['mimeType'] != FOLDER, item['name'].casefold(), item['name']))
            return {'files': files[offset:offset+100], 'nextPageToken': str(offset+100) if offset+100 < len(files) else None}

    def create_folder(self, parent, name):
        with self.lock:
            path = self.path(parent) / safe_name(name)
            try:
                path.mkdir()
            except FileExistsError:
                raise HTTPException(409, 'A file or folder with that name already exists.') from None
            return self.metadata(self.identifier(path))

    def upload_session(self, parent, name, size, mime):
        with self.lock:
            destination = self.path(parent) / safe_name(name)
            if destination.exists() or any(s['destination'] == destination for s in self.sessions.values()):
                raise HTTPException(409, 'A file with that name already exists. Rename the upload first.')
            key = uuid4().hex
            # OS-managed temporary file is removed on close or process exit.
            stream = tempfile.TemporaryFile(prefix='.locin-upload-', dir=destination.parent)
            self.sessions[key] = {'stream': stream, 'destination': destination, 'offset': 0, 'parent': parent}
            return key

    def upload_chunk(self, key, data, offset, total):
        with self.lock:
            item = self.sessions.get(key)
            if not item:
                raise HTTPException(404, 'Upload is no longer active.')
            if offset != item['offset']:
                raise HTTPException(409, 'Upload offset does not match.')
            item['stream'].write(data)
            item['offset'] += len(data)
            complete = item['offset'] == total
            if complete:
                self.path(item['parent'])
                created = False
                try:
                    with item['destination'].open('xb') as output:
                        created = True
                        item['stream'].seek(0)
                        shutil.copyfileobj(item['stream'], output, CHUNK)
                except FileExistsError:
                    raise HTTPException(409, 'A file with that name already exists. Rename the upload first.') from None
                except OSError:
                    if created:
                        item['destination'].unlink(missing_ok=True)
                    raise
                finally:
                    self.cancel_upload(key)
            return offset + len(data), complete

    def cancel_upload(self, key):
        with self.lock:
            item = self.sessions.pop(key, None)
            if item:
                item['stream'].close()

    def upload_status(self, key, total):
        with self.lock:
            item = self.sessions.get(key)
            if not item:
                raise HTTPException(404, 'Upload is no longer active.')
            return item['offset'], False

    def download(self, metadata):
        with self.lock:
            path = self.path(metadata['id'])
            if not path.is_file():
                raise HTTPException(400, 'Open the folder to download individual files.')
            response = LocalDownload(path)
            return response, response, path.name, metadata['mimeType']
