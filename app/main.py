import ipaddress
import json
import secrets
import threading
import time
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from google_auth_oauthlib.flow import Flow
from pydantic import BaseModel, Field
from .config import ROOT, CONTROL_PORT, FOLDER, valid_hostname, valid_id
from .database import Database
from .devices import active, touch
from .drive import Drive, DriveError, SCOPES
from .files import routes
from .network import Gateway
from .transfers import Transfers


class Runtime:
    def __init__(self, db=None, drive=None):
        self.db = db or Database()
        self.drive = drive or Drive()
        self.transfers = Transfers(self.db)
        self.gateway = Gateway(self)
        self.host_token = secrets.token_urlsafe(32)
        self.oauth = None
        self.oauth_lock = threading.Lock()
        self.settings_lock = threading.Lock()
        self.open_browser = None


class SettingsInput(BaseModel):
    local_name: str = Field(max_length=63)
    folder_id: str = Field(default='', max_length=200)
    start_at_login: bool = False


def create_app(runtime=None, host=True):
    runtime = runtime or Runtime()
    app = FastAPI(title='loc.in', docs_url=None, redoc_url=None, openapi_url=None)
    app.state.runtime = runtime
    db, drive, gateway = runtime.db, runtime.drive, runtime.gateway

    @app.exception_handler(DriveError)
    async def drive_error(request, exc):
        return JSONResponse({'detail': exc.message}, status_code=exc.status)

    @app.exception_handler(ValueError)
    async def input_error(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=400)

    @app.middleware('http')
    async def boundary(request, call_next):
        peer = request.client.host if request.client else ''
        hostname = request.url.hostname
        if host:
            if peer not in ('127.0.0.1', '::1') or hostname not in ('127.0.0.1', 'localhost'):
                return JSONResponse({'detail': 'Host controls are only available on this computer.'}, status_code=403)
        else:
            name = db.settings()['local_name']
            allowed_hosts = {gateway.ip, name + '.loc.in', name + '.local'}
            try:
                local = ipaddress.ip_address(peer) in ipaddress.ip_network(gateway.subnet)
            except ValueError:
                local = False
            if hostname not in allowed_hosts or not local:
                return JSONResponse({'detail': 'Connect to the same local network.'}, status_code=403)
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail': 'Cross-site requests are not allowed.'}, status_code=403)
        if request.headers.get('sec-fetch-site') == 'cross-site' and request.url.path.startswith('/api/'):
            return JSONResponse({'detail': 'Open loc.in directly to use this action.'}, status_code=403)
        if host and request.url.path.startswith('/api/'):
            token = request.headers.get('x-host-token') or request.cookies.get('locin_host', '')
            if not secrets.compare_digest(token, runtime.host_token):
                return JSONResponse({'detail': 'Open loc.in from the desktop application to access host controls.'}, status_code=401)
        if not host and request.url.path.startswith('/api/'):
            if gateway.state not in ('Running', 'Starting'):
                return JSONResponse({'detail': 'loc.in is stopped.'}, status_code=503)
            request.state.device = touch(db, peer, request.headers.get('user-agent', ''))
            if request.method not in ('GET', 'HEAD') and request.headers.get('x-locin-request') != '1':
                return JSONResponse({'detail': 'Invalid request.'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/')
    def index():
        return FileResponse(ROOT / 'frontend/index.html')

    @app.get('/mode')
    def mode():
        return {'host': host}

    app.mount('/assets', StaticFiles(directory=ROOT / 'frontend'), name='assets')

    @app.get('/api/status')
    def status():
        settings = db.settings()
        result = {'state': gateway.state, 'connected': bool(drive.credentials), 'unavailable': drive.unavailable,
                  'folder_name': settings['folder_name'], 'address': gateway.address(), 'host': host}
        if host:
            result.update({'email': drive.email, 'folder_id': settings['folder_id'], 'local_name': settings['local_name'],
                           'oauth_configured': drive.oauth_ready(), 'discovery_address': gateway.discovery_address(),
                           'fallback': f'http://{gateway.ip}:{gateway.port}' if gateway.ip else None,
                           'devices': len(active(db)), 'active_transfers': len(runtime.transfers.uploads) + len(runtime.transfers.downloads),
                           'error': gateway.error, 'warning': gateway.warning, 'start_at_login': settings['start_at_login']})
        return result

    app.include_router(routes(runtime, host))

    if host:
        @app.post('/api/auth/config')
        async def import_google_config(request: Request):
            payload = bytearray()
            async for chunk in request.stream():
                if len(payload) + len(chunk) > 16384:
                    raise HTTPException(413, 'Choose a Google Desktop app JSON file smaller than 16 KB.')
                payload.extend(chunk)
            try:
                config = json.loads(payload)
            except (ValueError, UnicodeDecodeError):
                raise HTTPException(400, 'This is not a valid JSON file. Download the Desktop app client JSON from Google.')
            def save_config():
                with runtime.oauth_lock:
                    if drive.credentials:
                        raise HTTPException(409, 'Google Drive is already connected. Keep the current app configuration.')
                    drive.import_oauth_config(config)
                    runtime.oauth = None
            await run_in_threadpool(save_config)
            return {'configured': True}

        @app.post('/api/session')
        def session():
            response = JSONResponse({'ok': True})
            response.set_cookie('locin_host', runtime.host_token, httponly=True, samesite='strict', path='/')
            return response

        @app.get('/api/settings')
        def settings():
            return db.settings()

        @app.put('/api/settings')
        def save_settings(body: SettingsInput):
            with runtime.settings_lock, gateway.lock:
                if gateway.state in ('Running', 'Starting') or runtime.transfers.uploads or runtime.transfers.downloads:
                    raise HTTPException(409, 'Stop loc.in and let transfers finish before changing settings.')
                name = valid_hostname(body.local_name)
                values = {'local_name': name, 'start_at_login': body.start_at_login}
                if body.folder_id:
                    folder = drive.metadata(valid_id(body.folder_id))
                    if folder['mimeType'] != FOLDER or folder.get('trashed'):
                        raise HTTPException(400, 'Choose an available Drive folder.')
                    values.update({'folder_id': folder['id'], 'folder_name': folder['name']})
                if body.start_at_login != db.settings()['start_at_login']:
                    from .startup import set_startup
                    set_startup(body.start_at_login)
                db.save(values)
            return db.settings()

        @app.post('/api/service/{action}')
        def service(action: str):
            if action == 'start':
                gateway.start()
            elif action == 'stop':
                gateway.stop()
            else:
                raise HTTPException(404, 'Unknown action.')
            return status()

        @app.get('/api/devices')
        def devices():
            return {'devices': active(db)}

        @app.get('/api/drive/folders')
        def folders(parent: str = 'root', page: str = ''):
            return drive.listing(valid_id(parent), page or None, folders_only=True)

        @app.post('/api/drive/default-folder')
        def default_folder():
            with runtime.settings_lock, gateway.lock:
                if gateway.state in ('Running', 'Starting') or runtime.transfers.uploads or runtime.transfers.downloads:
                    raise HTTPException(409, 'Stop loc.in before changing the shared folder.')
                folder = drive.default_folder()
                db.save({'folder_id': folder['id'], 'folder_name': folder['name']})
                return folder

        @app.post('/api/auth/google')
        def auth_google():
            with runtime.oauth_lock:
                flow = Flow.from_client_config(drive.oauth_config(), scopes=SCOPES, autogenerate_code_verifier=True)
                flow.redirect_uri = f'http://127.0.0.1:{CONTROL_PORT}/auth/callback'
                url, state = flow.authorization_url(access_type='offline', prompt='consent')
                runtime.oauth = (state, flow, time.time())
                opened = bool(runtime.open_browser and runtime.open_browser(url))
                return {'url': url, 'opened': opened}

        @app.get('/auth/callback')
        def callback(state: str = '', code: str = '', error: str = ''):
            with runtime.oauth_lock:
                pending = runtime.oauth
                if not pending or not secrets.compare_digest(state, pending[0]) or time.time() - pending[2] > 600:
                    raise HTTPException(400, 'This connection request expired. Return to loc.in and try again.')
                runtime.oauth = None
            if error or not code:
                return HTMLResponse('<h2>Google Drive was not connected.</h2><p>Return to loc.in to try again.</p>', status_code=400)
            try:
                flow = pending[1]
                flow.fetch_token(code=code)
                drive.save_credentials(flow.credentials)
            except DriveError:
                raise
            except Exception:
                raise HTTPException(400, 'Could not connect Google Drive. Return to loc.in and try again.')
            try:
                drive.account()
            except DriveError:
                pass
            return HTMLResponse('<html><head><title>Connected · loc.in</title></head><body><h2>Google Drive is connected.</h2><p>Return to loc.in to choose your folder and start sharing. You can close this tab.</p></body></html>')

    return app
