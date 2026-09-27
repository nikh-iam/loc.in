"""Run explicitly: python -m tests.browser_smoke (requires playwright + Edge).

All account/file data is synthetic. No Google traffic or LAN advertisement.
"""
import socket
import json
import tempfile
import threading
import time
from pathlib import Path
import uvicorn
from playwright.sync_api import sync_playwright, expect
from app.database import Database
from app.main import Runtime, create_app
from .fakes import FakeDrive


def main():
    with tempfile.TemporaryDirectory(prefix='locin-browser-') as directory:
        drive = FakeDrive()
        drive.credentials = None
        drive.email = None
        runtime = Runtime(Database(Path(directory) / 'locin.db'), drive)
        # Exercise UI state transitions without exposing the synthetic files on a LAN.
        def start():
            runtime.gateway.state = 'Running'
            runtime.gateway.ip = '192.168.10.2'
        def stop():
            runtime.gateway.state = 'Stopped'
        runtime.gateway.start = start
        runtime.gateway.stop = stop
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
        listener.listen(128)
        server = uvicorn.Server(uvicorn.Config(create_app(runtime), access_log=False, log_level='error', proxy_headers=False))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(.05)
        assert server.started
        artifacts = Path('data/screenshots')
        artifacts.mkdir(parents=True, exist_ok=True)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(channel='msedge', headless=True)
                context = browser.new_context(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{port}/#token={runtime.host_token}')
                expect(page.locator('#preloader')).to_be_visible()
                expect(page.get_by_role('heading', name='Your files. Your network.', exact=True)).to_be_visible()
                assert page.locator('.app').get_attribute('inert') is not None
                page.screenshot(path=str(artifacts / 'preloader-desktop.png'), full_page=True)
                expect(page.locator('#preloader')).to_have_count(0, timeout=15000)
                expect(page.locator('.app')).to_have_attribute('aria-busy', 'false')
                expect(page.get_by_role('heading', name='Your Drive. Meet your network.')).to_be_visible()
                expect(page.get_by_role('button', name='Start loc.in', exact=True)).to_be_disabled()
                page.screenshot(path=str(artifacts / 'setup-desktop.png'), full_page=True)
                page.locator('[data-action="storage-local"]').click()
                expect(page.locator('.setup-layout')).to_be_visible()
                expect(page.locator('.setup-aside')).to_be_visible()
                expect(page.get_by_text('The local folder is unavailable. Check it on the host.', exact=True)).to_have_count(0)
                expect(page.get_by_role('button', name='Start loc.in', exact=True)).to_be_disabled()
                page.screenshot(path=str(artifacts / 'local-setup-desktop.png'), full_page=True)
                page.locator('[data-action="storage-drive"]').click()
                page.get_by_role('button', name='Connect Google Drive', exact=True).click()
                expect(page.get_by_role('heading', name='Set up Google Drive', exact=True)).to_be_visible()
                expect(page.get_by_role('button', name='Import Google JSON', exact=True)).to_be_visible()
                from .test_oauth_setup import desktop_config
                page.locator('#oauth-picker').set_input_files({'name': 'desktop-client.json', 'mimeType': 'application/json', 'buffer': json.dumps(desktop_config()).encode()})
                expect(page.get_by_role('status').filter(has_text='Google configuration saved.')).to_be_visible()
                assert drive.configured
                page.get_by_label('Local name', exact=True).fill('vault')
                page.get_by_role('heading', name='Your Drive. Meet your network.').click()
                drive.credentials = object()
                drive.email = 'test@example.invalid'
                expect(page.get_by_role('button', name='Use My Drive / loc.in')).to_be_enabled(timeout=10000)
                expect(page.get_by_label('Local name', exact=True)).to_have_value('vault')
                page.get_by_role('button', name='Use My Drive / loc.in').click()
                expect(page.get_by_role('heading', name='A home for your files.')).to_be_visible()
                expect(page.get_by_role('button', name='Start loc.in', exact=True)).to_be_enabled()
                page.get_by_role('button', name='Start loc.in', exact=True).click()
                expect(page.get_by_role('button', name='Open loc.in', exact=True)).to_be_visible()
                expect(page.get_by_text('vault.loc.in', exact=True)).to_have_count(2)
                page.get_by_role('button', name='Setup instructions', exact=True).click()
                expect(page.get_by_role('heading', name='Set up your custom address', exact=True)).to_be_visible()
                expect(page.get_by_text('A record', exact=True)).to_be_visible()
                page.get_by_role('button', name='Done', exact=True).click()
                page.screenshot(path=str(artifacts / 'home-desktop.png'), full_page=True)
                page.get_by_role('button', name='Files', exact=True).click()
                expect(page.get_by_role('button', name='Welcome.txt', exact=True)).to_be_visible()
                page.get_by_role('button', name='Photos', exact=True).click()
                expect(page.get_by_role('heading', name='A little room for something new.')).to_be_visible()
                page.get_by_role('button', name='New folder', exact=True).click()
                page.get_by_label('Folder name', exact=True).fill('Summer')
                page.get_by_role('button', name='Create folder', exact=True).click()
                expect(page.get_by_role('button', name='Summer', exact=True)).to_be_visible()
                page.locator('[data-crumb="-1"]').click()
                page.get_by_label('Search this folder').fill('Welcome')
                expect(page.get_by_role('button', name='Welcome.txt', exact=True)).to_be_visible()
                expect(page.get_by_role('button', name='Photos', exact=True)).to_have_count(0)
                with page.expect_download() as download:
                    page.get_by_role('link', name='Download Welcome.txt', exact=True).click()
                assert download.value.suggested_filename == 'Welcome.txt'
                assert Path(download.value.path()).read_bytes() == b'Welcome to your local space!'
                page.get_by_label('Search this folder').fill('')
                page.locator('#file-picker').set_input_files({'name': 'browser-test.txt', 'mimeType': 'text/plain', 'buffer': b'Browser upload test'})
                expect(page.get_by_role('button', name='browser-test.txt', exact=True)).to_be_visible(timeout=15000)
                page.screenshot(path=str(artifacts / 'files-desktop.png'), full_page=True)
                page.get_by_role('button', name='Settings', exact=True).click()
                expect(page.get_by_role('button', name='Save changes', exact=True)).to_be_disabled()
                page.get_by_role('button', name='Home', exact=True).click()
                page.get_by_role('button', name='Stop service', exact=True).click()
                expect(page.get_by_role('button', name='Start loc.in', exact=True)).to_be_visible()
                page.get_by_role('button', name='Settings', exact=True).click()
                page.get_by_label('Local name', exact=True).fill('homebox')
                page.get_by_role('button', name='Save changes', exact=True).click()
                expect(page.get_by_role('status').filter(has_text='Your settings are saved.')).to_be_visible()
                assert runtime.db.settings()['local_name'] == 'homebox'
                page.set_viewport_size({'width': 390, 'height': 844})
                page.get_by_role('button', name='Files', exact=True).click()
                expect(page.get_by_role('button', name='Welcome.txt', exact=True)).to_be_visible()
                page.screenshot(path=str(artifacts / 'files-mobile.png'), full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                page.get_by_role('button', name='Devices', exact=True).click()
                expect(page.get_by_role('heading', name='Good company.')).to_be_visible()
                page.screenshot(path=str(artifacts / 'devices-mobile.png'), full_page=True)
                page.get_by_role('button', name='About', exact=True).click()
                expect(page.get_by_role('heading', name='About loc.in', exact=True)).to_be_visible()
                expect(page.get_by_role('heading', name='Who can access your files?', exact=True)).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                page.screenshot(path=str(artifacts / 'about-mobile.png'), full_page=True)
                # Use a real temporary host folder, without Google credentials.
                local_folder = Path(directory) / 'Shared'
                local_folder.mkdir()
                drive.credentials = None
                page.get_by_role('button', name='Settings', exact=True).click()
                page.locator('[data-action="storage-local"]').click()
                expect(page.get_by_label('Storage location').locator('[aria-pressed="true"]')).to_contain_text('Local storage')
                page.get_by_role('button', name='Choose folder', exact=True).click()
                page.get_by_label('Folder path', exact=True).fill(str(local_folder))
                page.get_by_role('button', name='Share this folder', exact=True).click()
                expect(page.get_by_role('status').filter(has_text='Local folder ready')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                page.screenshot(path=str(artifacts / 'local-settings-mobile.png'), full_page=True)
                page.get_by_role('button', name='Home', exact=True).click()
                page.get_by_role('button', name='Start loc.in', exact=True).click()
                expect(page.get_by_role('button', name='Open loc.in', exact=True)).to_be_visible()
                page.get_by_role('button', name='Files', exact=True).click()
                page.locator('#file-picker').set_input_files({'name': 'local-test.txt', 'mimeType': 'text/plain', 'buffer': b'Offline local upload'})
                expect(page.get_by_role('button', name='local-test.txt', exact=True)).to_be_visible(timeout=15000)
                assert (local_folder / 'local-test.txt').read_bytes() == b'Offline local upload'
                with page.expect_download() as local_download:
                    page.get_by_role('link', name='Download local-test.txt', exact=True).click()
                assert Path(local_download.value.path()).read_bytes() == b'Offline local upload'
                # Lose an acknowledged reply, pause mid-file, reload, and reselect
                # the same physical file. Only the unacknowledged tail is sent.
                from app.config import CHUNK
                large_file = Path(directory) / 'resume-test.bin'
                large_file.write_bytes(b'a' * CHUNK + b'b' * CHUNK + b'finished')
                offsets, held = [], []
                lost_reply = [False]
                def interrupt_upload(route):
                    if route.request.method != 'PUT':
                        route.continue_()
                        return
                    from urllib.parse import urlparse, parse_qs
                    offset = int(parse_qs(urlparse(route.request.url).query).get('offset', ['0'])[0])
                    offsets.append(offset)
                    if offset == 0 and not lost_reply[0]:
                        route.fetch()
                        lost_reply[0] = True
                        route.abort('failed')
                    elif offset == CHUNK and not held:
                        held.append(route)
                    else:
                        route.continue_()
                page.route('**/api/files/upload/*', interrupt_upload)
                page.locator('#file-picker').set_input_files(str(large_file))
                page.get_by_role('button', name='Home', exact=True).click()
                page.locator('[data-nav="transfers"]').click()
                expect(page.get_by_role('button', name='Pause', exact=True)).to_be_visible(timeout=15000)
                page.get_by_role('button', name='Pause', exact=True).click()
                # If Pause was clicked during the retry delay, the second chunk
                # has not started yet. Either path must retain acknowledged bytes.
                if held:
                    held[0].continue_()
                expect(page.get_by_role('button', name='Resume upload', exact=True)).to_be_visible(timeout=15000)
                assert runtime.transfers.uploads
                key = next(iter(runtime.transfers.uploads))
                acknowledged = runtime.transfers.uploads[key]['offset']
                assert acknowledged >= CHUNK
                page.reload()
                expect(page.locator('#preloader')).to_have_count(0, timeout=15000)
                page.get_by_role('button', name='Files', exact=True).click()
                page.unroute('**/api/files/upload/*', interrupt_upload)
                resumed_offsets = []
                def record_resume(route):
                    if route.request.method == 'PUT':
                        from urllib.parse import urlparse, parse_qs
                        resumed_offsets.append(int(parse_qs(urlparse(route.request.url).query)['offset'][0]))
                    route.continue_()
                page.route('**/api/files/upload/*', record_resume)
                page.locator('#file-picker').set_input_files(str(large_file))
                expect(page.get_by_role('button', name='resume-test.bin', exact=True)).to_be_visible(timeout=20000)
                assert resumed_offsets[0] == acknowledged
                assert offsets.count(0) == 1
                assert (local_folder / 'resume-test.bin').read_bytes() == large_file.read_bytes()
                assert any(t['id'] == key and t['status'] == 'Completed' for t in runtime.transfers.list())
                page.unroute('**/api/files/upload/*', record_resume)
                page.get_by_role('button', name='Home', exact=True).click()
                page.get_by_role('button', name='Stop service', exact=True).click()
                page.get_by_role('button', name='Settings', exact=True).click()
                page.locator('[data-action="storage-drive"]').click()
                expect(page.get_by_label('Storage location').locator('[aria-pressed="true"]')).to_contain_text('Google Drive')
                assert (local_folder / 'local-test.txt').exists()
                page.locator('[data-action="storage-local"]').click()
                expect(page.get_by_label('Storage location').locator('[aria-pressed="true"]')).to_contain_text('Local storage')
                # Same static shell selects the minimal client navigation from /mode.
                page.get_by_role('button', name='Protect shared folder', exact=True).click()
                page.get_by_label('Folder password', exact=True).fill('browser-password')
                page.get_by_role('button', name='Save password', exact=True).click()
                expect(page.get_by_role('button', name='Manage password', exact=True)).to_be_visible()
                # Simulate the protected client response while serving the shell
                # on loopback; backend LAN authorization has separate API tests.
                denied = [True]
                def protected_listing(route):
                    if denied[0]:
                        route.fulfill(status=423,json={'detail':'Enter the password to open this folder.','folder_id':'local_root'})
                    else:
                        route.continue_()
                def unlock_client(route):
                    response=route.fetch()
                    if response.status==200:
                        denied[0]=False
                    route.fulfill(response=response)
                page.route('**/api/files?*',protected_listing)
                page.route('**/api/folders/unlock',unlock_client)
                page.route('**/mode', lambda route: route.fulfill(json={'host': False}))
                page.reload()
                expect(page.get_by_role('heading',name='Protected folder',exact=True)).to_be_visible()
                page.get_by_label('Folder password',exact=True).fill('browser-password')
                page.get_by_role('button',name='Unlock folder',exact=True).click()
                expect(page.get_by_role('button',name='local-test.txt',exact=True)).to_be_visible()
                expect(page.get_by_role('button', name='Files', exact=True)).to_be_visible()
                expect(page.get_by_role('button', name='Settings', exact=True)).to_have_count(0)
                expect(page.get_by_role('button', name='Transfers', exact=True)).to_be_visible()
                page.get_by_role('button', name='Transfers', exact=True).click()
                expect(page.get_by_role('heading', name='A little back and forth.')).to_be_visible()
                page.screenshot(path=str(artifacts / 'transfers-mobile.png'), full_page=True)
                assert not errors, errors
                failed = context.new_page()
                failed.emulate_media(reduced_motion='reduce')
                failed.set_viewport_size({'width': 390, 'height': 844})
                failed.route('**/mode', lambda route: route.fulfill(status=503, json={'detail': 'Host unavailable.'}))
                failed.goto(f'http://127.0.0.1:{port}/')
                expect(failed.locator('#preloader')).to_have_count(0)
                expect(failed.get_by_role('button', name='Try again', exact=True)).to_be_visible()
                failed.close()
                stalled = context.new_page()
                stalled.set_viewport_size({'width': 390, 'height': 844})
                stalled_routes = []
                stalled.route('**/mode', lambda route: stalled_routes.append(route))
                stalled.goto(f'http://127.0.0.1:{port}/')
                expect(stalled.locator('#preloader')).to_be_visible()
                assert stalled.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                stalled.screenshot(path=str(artifacts / 'preloader-mobile.png'), full_page=True)
                expect(stalled.get_by_role('button', name='Try again', exact=True)).to_be_visible(timeout=15000)
                expect(stalled.locator('#preloader')).to_have_count(0)
                for route in stalled_routes:
                    route.abort()
                stalled.close()
                browser.close()
        finally:
            server.should_exit = True
            thread.join(10)
            listener.close()
    print('Browser checks passed: onboarding, draft retention, service controls, folders, search, upload, download, settings, desktop/mobile layouts, client navigation; no JavaScript errors.')


if __name__ == '__main__':
    main()
