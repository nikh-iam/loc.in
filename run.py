"""loc.in entry point: native window + tray, or a browser during development."""
import argparse
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
import uvicorn
from app.config import CONTROL_PORT
from app.main import Runtime, create_app


def tray_image():
    from PIL import Image, ImageDraw
    image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2, 2, 62, 62), radius=17, fill='#314b36')
    draw.line((20, 15, 20, 48, 44, 48), fill='#d9ecab', width=5)
    draw.line((31, 20, 47, 20, 47, 36), fill='#d9ecab', width=4)
    draw.line((31, 36, 47, 20), fill='#d9ecab', width=4)
    return image


def notify_error(message):
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, 'loc.in', 0x10)
    elif sys.stderr:
        print(message, file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description='Your local Google Drive gateway.')
    parser.add_argument('--browser', action='store_true', help='Use the default browser instead of a desktop window.')
    parser.add_argument('--background', action='store_true', help='Start in the system tray.')
    parser.add_argument('--no-window', action='store_true', help='Run only the loopback host server; for development.')
    parser.add_argument('--smoke-test', action='store_true', help='Check the packaged host server and exit without opening a window.')
    args = parser.parse_args()
    # Frozen windowed builds have no console streams. Avoid logger formatter errors.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w')
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        listener.bind(('127.0.0.1', 0 if args.smoke_test else CONTROL_PORT))
        listener.listen(128)
        listener.setblocking(False)
    except OSError:
        listener.close()
        notify_error('loc.in is already open, or its host port is in use. Look for loc.in in your system tray.')
        return 1
    port = listener.getsockname()[1]
    runtime = Runtime()
    runtime.open_browser = webbrowser.open
    url = f'http://127.0.0.1:{port}/#token={runtime.host_token}'
    server = uvicorn.Server(uvicorn.Config(create_app(runtime), access_log=False, log_level='warning', proxy_headers=False, timeout_graceful_shutdown=5))
    worker = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    worker.start()
    deadline = time.monotonic() + 10
    while not server.started and worker.is_alive() and time.monotonic() < deadline:
        time.sleep(.05)
    if not server.started:
        notify_error('The host interface could not start. Please reopen loc.in.')
        server.should_exit = True
        listener.close()
        return 1
    closed = threading.Event()
    tray = None
    window = None

    def maintain():
        while not closed.wait(30):
            runtime.transfers.reap()

    def show_window(*_):
        if window:
            window.show()
            window.restore()
        else:
            webbrowser.open(url)

    def exit_app(*_):
        closed.set()
        if tray:
            tray.stop()
        if window:
            window.destroy()

    try:
        if args.smoke_test:
            import httpx
            with httpx.Client(trust_env=False) as client:
                response = client.get(f'http://127.0.0.1:{port}/api/status', headers={'X-Host-Token': runtime.host_token})
                response.raise_for_status()
                assert response.json()['host'] is True
                assert client.get(f'http://127.0.0.1:{port}/assets/app.js').status_code == 200
            return 0
        threading.Thread(target=maintain, daemon=True).start()
        if runtime.db.settings()['start_at_login']:
            threading.Thread(target=runtime.gateway.start, daemon=True).start()
        if not args.no_window:
            if not args.browser:
                import webview
                webview.settings['ALLOW_DOWNLOADS'] = True
                window = webview.create_window('loc.in', url, width=1220, height=850, min_size=(720, 560), background_color='#f7f8f5', hidden=args.background)
                def pick_folder():
                    selected = window.create_file_dialog(webview.FileDialog.FOLDER)
                    return selected[0] if selected else None
                runtime.pick_folder = pick_folder
            try:
                import pystray
                tray = pystray.Icon('loc.in', tray_image(), 'loc.in — Your local Drive', menu=pystray.Menu(
                    pystray.MenuItem('Open loc.in', show_window, default=True),
                    pystray.MenuItem('Open local address', lambda: webbrowser.open(runtime.gateway.address()), enabled=lambda _: runtime.gateway.state == 'Running'),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem('Start', lambda: threading.Thread(target=runtime.gateway.start, daemon=True).start(), enabled=lambda _: runtime.gateway.state not in ('Running', 'Starting')),
                    pystray.MenuItem('Stop', lambda: threading.Thread(target=runtime.gateway.stop, daemon=True).start(), enabled=lambda _: runtime.gateway.state == 'Running'),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem('Exit', exit_app),
                ))
                tray.run_detached()
            except Exception:
                tray = None
                if window and args.background:
                    window.show()
            if window:
                def closing():
                    if tray and not closed.is_set():
                        window.hide()
                        return False
                    closed.set()
                window.events.closing += closing
                try:
                    webview.start(private_mode=True)
                except Exception:
                    window = None
                    webbrowser.open(url)
                    while not closed.wait(.5):
                        pass
            else:
                if not args.background or not tray:
                    webbrowser.open(url)
                while not closed.wait(.5):
                    pass
        else:
            print(f'loc.in host is listening on 127.0.0.1:{CONTROL_PORT}. Use --browser for an authenticated interface.')
            while worker.is_alive() and not closed.wait(.5):
                pass
    except KeyboardInterrupt:
        pass
    finally:
        closed.set()
        if tray:
            tray.stop()
        runtime.gateway.stop()
        server.should_exit = True
        worker.join(timeout=7)
        listener.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
