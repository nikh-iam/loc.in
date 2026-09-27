"""Isolated Drive substitute for tests only; never wired into production."""
import hashlib
import threading
import httpx
from app.config import FOLDER
from app.drive import Drive, DriveError


class FakeDrive(Drive):
    def __init__(self):
        self.credentials = object()
        self.email = 'test@example.invalid'
        self.unavailable = False
        self.lock = threading.RLock()
        self.items = {
            'root': {'id': 'root', 'name': 'My Drive', 'mimeType': FOLDER},
            'shared': {'id': 'shared', 'name': 'loc.in', 'mimeType': FOLDER, 'parents': ['root']},
            'photos': {'id': 'photos', 'name': 'Photos', 'mimeType': FOLDER, 'parents': ['shared']},
            'file1': {'id': 'file1', 'name': 'Welcome.txt', 'mimeType': 'text/plain', 'size': '24', 'parents': ['shared'], 'modifiedTime': '2026-09-01T12:00:00Z'},
            'private': {'id': 'private', 'name': 'Private', 'mimeType': FOLDER, 'parents': ['root']},
            'private-file': {'id': 'private-file', 'name': 'secret.txt', 'mimeType': 'text/plain', 'parents': ['private']},
            'shortcut': {'id': 'shortcut', 'name': 'Shortcut', 'mimeType': 'application/vnd.google-apps.shortcut', 'parents': ['shared']},
        }
        self.sessions = {}
        self.received_sizes = []
        self.list_calls = []
        self.download_closed = False
        self.configured = False

    def oauth_ready(self):
        return self.configured

    def import_oauth_config(self, config):
        self.validate_oauth_config(config)
        self.configured = True

    def metadata(self, file_id):
        if self.unavailable:
            raise DriveError('Google Drive is currently unavailable. loc.in is still running on your local network.')
        if not self.credentials:
            raise DriveError('Google Drive disconnected. Reconnect Google Drive from the host application.', 401)
        if file_id not in self.items:
            raise DriveError('This file or folder is no longer available.', 404)
        return dict(self.items[file_id])

    def listing(self, parent, page=None, search='', folders_only=False):
        self.list_calls.append((parent, page, search, folders_only))
        rows = [dict(f) for f in self.items.values() if parent in f.get('parents', []) and not f.get('trashed') and search.lower() in f['name'].lower() and (not folders_only or f['mimeType'] == FOLDER)]
        return {'files': rows}

    def create_folder(self, parent, name):
        key = 'new-' + str(len(self.items))
        self.items[key] = {'id': key, 'name': name, 'mimeType': FOLDER, 'parents': [parent]}
        return dict(self.items[key])

    def default_folder(self):
        return dict(self.items['shared'])

    def upload_session(self, parent, name, size, mime):
        url = 'https://www.googleapis.com/upload/test-' + str(len(self.sessions))
        self.sessions[url] = {'parent': parent, 'name': name, 'size': size, 'mime': mime, 'hash': hashlib.sha256(), 'offset': 0}
        return url

    def upload_chunk(self, url, data, offset, total):
        item = self.sessions[url]
        assert offset == item['offset']
        item['hash'].update(data)
        item['offset'] += len(data)
        self.received_sizes.append(len(data))
        done = item['offset'] == total
        if done:
            key = 'upload-' + str(len(self.items))
            self.items[key] = {'id': key, 'name': item['name'], 'mimeType': item['mime'], 'size': str(total), 'parents': [item['parent']]}
        return item['offset'], done

    def download(self, metadata):
        if metadata['mimeType'] == FOLDER or metadata['mimeType'].startswith('application/vnd.google-apps.'):
            raise DriveError('This item cannot be downloaded.', 400)
        parent = self

        class Stream(httpx.SyncByteStream):
            def __iter__(self):
                yield b'Welcome to your local '
                yield b'space!'

            def close(self):
                parent.download_closed = True

        client = httpx.Client()
        response = httpx.Response(200, stream=Stream(), headers={'content-length': '28'})
        return client, response, metadata['name'], metadata['mimeType']

    def upload_status(self, url, total):
        count = self.sessions[url]['offset']
        return count, count == total
