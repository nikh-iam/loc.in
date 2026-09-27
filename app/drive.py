"""Google Drive adapter. Never return credentials or resumable URLs to a client."""
import json
import os
import threading
from urllib.parse import urlparse
import httpx
import keyring
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError, TransportError
from google.oauth2.credentials import Credentials
from .config import ROOT, FOLDER, valid_id

SCOPES = ['https://www.googleapis.com/auth/drive']
API = 'https://www.googleapis.com/drive/v3'
FIELDS = 'id,name,mimeType,size,modifiedTime,parents,trashed'
EXPORTS = {
    'application/vnd.google-apps.document': ('application/pdf', '.pdf'),
    'application/vnd.google-apps.spreadsheet': ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.xlsx'),
    'application/vnd.google-apps.presentation': ('application/vnd.openxmlformats-officedocument.presentationml.presentation', '.pptx'),
}


class DriveError(Exception):
    def __init__(self, message, status=503):
        self.message, self.status = message, status
        super().__init__(message)


class Drive:
    def __init__(self):
        self.lock = threading.RLock()
        self.credentials = None
        self.email = None
        self.unavailable = False
        try:
            saved = keyring.get_password('loc.in', 'google-oauth')
            if saved:
                self.credentials = Credentials.from_authorized_user_info(json.loads(saved), SCOPES)
        except (keyring.errors.KeyringError, ValueError):
            pass

    def oauth_config(self):
        try:
            saved = keyring.get_password('loc.in', 'google-client')
        except keyring.errors.KeyringError:
            saved = None
        if saved:
            try:
                return self.validate_oauth_config(json.loads(saved))
            except (ValueError, TypeError):
                raise DriveError('The saved Google configuration is invalid. Import a Desktop app JSON file in Settings.', 400)
        path = os.environ.get('LOCIN_OAUTH_CLIENT', str(ROOT / 'oauth-client.json'))
        try:
            with open(path, encoding='utf-8') as f:
                config = json.load(f)
            return self.validate_oauth_config(config)
        except (OSError, ValueError, TypeError):
            raise DriveError('Google setup is needed. Import your Google Desktop app JSON file to connect Drive.', 503)

    @staticmethod
    def validate_oauth_config(config):
        installed = config.get('installed') if isinstance(config, dict) else None
        if not isinstance(installed, dict):
            raise ValueError('Choose the JSON downloaded for a Google OAuth Desktop app, not a web app or service account.')
        client_id, secret = installed.get('client_id'), installed.get('client_secret')
        if not isinstance(client_id, str) or not client_id.endswith('.apps.googleusercontent.com') or len(client_id) > 256 or not isinstance(secret, str) or not 1 <= len(secret) <= 256:
            raise ValueError('The file is missing a valid Google client ID or client secret.')
        if any(ord(c) < 33 for c in client_id + secret):
            raise ValueError('Invalid Google client configuration.')
        # Never trust imported authorization/token URLs: both receive credentials.
        if installed.get('auth_uri') != 'https://accounts.google.com/o/oauth2/auth' or installed.get('token_uri') != 'https://oauth2.googleapis.com/token':
            raise ValueError('Choose an original Google Desktop app JSON file with Google authorization endpoints.')
        return {'installed': {'client_id': client_id, 'client_secret': secret,
                              'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                              'token_uri': 'https://oauth2.googleapis.com/token',
                              'redirect_uris': ['http://localhost']}}

    def import_oauth_config(self, config):
        clean = self.validate_oauth_config(config)
        try:
            keyring.set_password('loc.in', 'google-client', json.dumps(clean))
        except keyring.errors.KeyringError:
            raise DriveError('The operating system credential vault is unavailable. The configuration could not be saved.')

    def oauth_ready(self):
        try:
            self.oauth_config()
            return True
        except DriveError:
            return False

    def save_credentials(self, credentials):
        try:
            keyring.set_password('loc.in', 'google-oauth', credentials.to_json())
        except keyring.errors.KeyringError:
            raise DriveError('The operating system credential vault is unavailable. Your Google connection could not be saved.')
        self.credentials = credentials

    def token(self):
        with self.lock:
            if not self.credentials:
                raise DriveError('Google Drive disconnected. Reconnect Google Drive from the host application.', 401)
            try:
                if not self.credentials.valid:
                    self.credentials.refresh(Request())
                    self.save_credentials(self.credentials)
            except RefreshError:
                self.credentials = None
                raise DriveError('Google Drive disconnected. Reconnect Google Drive from the host application.', 401)
            except TransportError:
                self.unavailable = True
                raise DriveError('Google Drive is currently unavailable. loc.in is still running on your local network.')
            return self.credentials.token

    def check(self, response):
        if response.status_code in (200, 201, 204, 308):
            self.unavailable = False
            return
        if response.status_code == 401:
            self.credentials = None
            raise DriveError('Google Drive disconnected. Reconnect Google Drive from the host application.', 401)
        if response.status_code == 404:
            raise DriveError('This file or folder is no longer available.', 404)
        if response.status_code == 403:
            try:
                reasons = {item.get('reason') for item in response.json().get('error', {}).get('errors', [])}
            except (ValueError, AttributeError, TypeError):
                reasons = set()
            if reasons & {'rateLimitExceeded', 'userRateLimitExceeded'}:
                raise DriveError('Google Drive is busy. This upload can resume shortly.', 429)
            raise DriveError('Google Drive denied this operation. Check the folder permissions and account limits.', 403)
        if response.status_code == 429:
            raise DriveError('Google Drive is busy. This upload can resume shortly.', 429)
        self.unavailable = True
        raise DriveError('Google Drive is currently unavailable. loc.in is still running on your local network.')

    def request(self, method, path, **kwargs):
        try:
            with httpx.Client(timeout=60) as client:
                response = client.request(method, path if path.startswith('https://') else API + path,
                                          headers={'Authorization': 'Bearer ' + self.token(), **kwargs.pop('headers', {})}, **kwargs)
            self.check(response)
            return response
        except httpx.HTTPError:
            self.unavailable = True
            raise DriveError('Google Drive is currently unavailable. loc.in is still running on your local network.')

    def metadata(self, file_id):
        return self.request('GET', '/files/' + valid_id(file_id), params={'fields': FIELDS}).json()

    def contained(self, file_id, root, folder=False):
        if not root:
            raise DriveError('Choose a shared Drive folder from the host application.', 409)
        valid_id(file_id)
        original = current = self.metadata(file_id)
        seen = set()
        # Do not follow shortcuts. Validate ancestry for every operation, not only listings.
        for _ in range(128):
            if current.get('trashed'):
                break
            if current['id'] == root:
                if folder and original['mimeType'] != FOLDER:
                    raise DriveError('Choose a folder.', 400)
                return original
            if current['id'] in seen or not current.get('parents'):
                break
            seen.add(current['id'])
            current = self.metadata(current['parents'][0])
        raise DriveError('This item is outside the shared folder.', 403)

    def listing(self, parent, page=None, search='', folders_only=False):
        valid_id(parent)
        query = f"'{parent}' in parents and trashed = false"
        if folders_only:
            query += f" and mimeType = '{FOLDER}'"
        if search:
            escaped = search.replace('\\', '\\\\').replace("'", "\\'")
            query += f" and name contains '{escaped}'"
        params = {'q': query, 'fields': 'nextPageToken,files(id,name,mimeType,size,modifiedTime)', 'pageSize': 100, 'orderBy': 'folder,name'}
        if page:
            params['pageToken'] = page
        return self.request('GET', '/files', params=params).json()

    def create_folder(self, parent, name):
        return self.request('POST', '/files', params={'fields': FIELDS}, json={'name': name, 'mimeType': FOLDER, 'parents': [parent]}).json()

    def default_folder(self):
        response = self.request('GET', '/files', params={'q': f"'root' in parents and name = 'loc.in' and mimeType = '{FOLDER}' and trashed = false", 'fields': 'files(id,name)', 'pageSize': 1}).json()
        return response['files'][0] if response.get('files') else self.create_folder('root', 'loc.in')

    def account(self):
        data = self.request('GET', '/about', params={'fields': 'user(emailAddress)'}).json()
        self.email = data.get('user', {}).get('emailAddress')

    def upload_session(self, parent, name, size, mime):
        r = self.request('POST', 'https://www.googleapis.com/upload/drive/v3/files', params={'uploadType': 'resumable', 'fields': 'id,name,size'},
                         headers={'X-Upload-Content-Type': mime, 'X-Upload-Content-Length': str(size)}, json={'name': name, 'parents': [parent]})
        url = r.headers.get('location', '')
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname != 'www.googleapis.com':
            raise DriveError('Google Drive did not return a valid upload session.')
        return url

    def upload_chunk(self, url, data, offset, total):
        content_range = f'bytes {offset}-{offset + len(data) - 1}/{total}' if total else 'bytes */0'
        response = self.request('PUT', url, content=data, headers={'Content-Range': content_range, 'Content-Type': 'application/octet-stream'})
        if response.status_code == 308:
            received = response.headers.get('range', '')
            count = int(received.rsplit('-', 1)[-1]) + 1 if received else 0
            return count, False
        return total, True

    def upload_status(self, url, total):
        response = self.request('PUT', url, content=b'', headers={'Content-Range': f'bytes */{total}', 'Content-Length': '0'})
        if response.status_code == 308:
            received = response.headers.get('range', '')
            return (int(received.rsplit('-', 1)[-1]) + 1 if received else 0), False
        return total, True

    def download(self, metadata):
        mime = metadata['mimeType']
        if mime == FOLDER:
            raise DriveError('Open the folder to download its files.', 400)
        filename = metadata['name']
        params = {'alt': 'media'}
        path = '/files/' + valid_id(metadata['id'])
        if mime in EXPORTS:
            mime, extension = EXPORTS[mime]
            path += '/export'
            params = {'mimeType': mime}
            filename += extension
        elif mime.startswith('application/vnd.google-apps.'):
            raise DriveError('This Google Drive file type cannot be downloaded here.', 400)
        client = httpx.Client(timeout=60)
        try:
            response = client.send(client.build_request('GET', API + path, params=params, headers={'Authorization': 'Bearer ' + self.token()}), stream=True)
            self.check(response)
            return client, response, filename, mime
        except Exception as exc:
            client.close()
            if isinstance(exc, httpx.HTTPError):
                raise DriveError('Google Drive is currently unavailable. Try the download again.')
            raise
