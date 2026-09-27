import ipaddress
import socket
import threading
import time
import psutil
import uvicorn
from zeroconf import IPVersion, ServiceInfo, Zeroconf


def local_interface():
    candidates = []
    stats = psutil.net_if_stats()
    for name, addresses in psutil.net_if_addrs().items():
        if name not in stats or not stats[name].isup:
            continue
        for address in addresses:
            if address.family == socket.AF_INET and address.netmask:
                ip = ipaddress.ip_address(address.address)
                if ip.is_private and not ip.is_loopback and not ip.is_link_local:
                    candidates.append((address.address, str(ipaddress.ip_network(f'{address.address}/{address.netmask}', strict=False))))
    if not candidates:
        raise RuntimeError('Connect this computer to Wi-Fi or Ethernet, then try again.')
    # Ask the OS which adapter carries the default route; UDP connect sends no packet.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
            route.connect(('8.8.8.8', 80))
            preferred = route.getsockname()[0]
        return next((item for item in candidates if item[0] == preferred), candidates[0])
    except OSError:
        return candidates[0]


class Gateway:
    def __init__(self, runtime):
        self.runtime = runtime
        self.state = 'Stopped'
        self.error = None
        self.warning = None
        self.ip = None
        self.subnet = None
        self.port = 80
        self.server = None
        self.thread = None
        self.zc = None
        self.info = None
        self.lock = threading.Lock()

    def address(self):
        name = self.runtime.db.settings()['local_name']
        suffix = '' if self.port == 80 else f':{self.port}'
        return f'http://{name}.local{suffix}'

    def custom_address(self):
        name = self.runtime.db.settings()['local_name']
        suffix = '' if self.port == 80 else f':{self.port}'
        return f'http://{name}.loc.in{suffix}'

    def fallback(self):
        if not self.ip:
            return None
        suffix = '' if self.port == 80 else f':{self.port}'
        return f'http://{self.ip}{suffix}'

    def start(self):
        with self.lock:
            if self.state in ('Starting', 'Running'):
                return
            self.state, self.error, self.warning = 'Starting', None, None
            listener = None
            try:
                if self.runtime.db.settings()['storage_mode'] == 'local':
                    self.runtime.local.root()
                elif not self.runtime.drive.credentials or not self.runtime.db.settings()['folder_id']:
                    raise RuntimeError('Connect Google Drive and choose a folder first.')
                self.ip, self.subnet = local_interface()
                for port in (80, 8000):
                    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    try:
                        listener.bind((self.ip, port))
                        listener.listen(128)
                        listener.setblocking(False)
                        self.port = port
                        break
                    except OSError:
                        listener.close()
                        listener = None
                if listener is None:
                    raise RuntimeError('Ports 80 and 8000 are in use. Close the other local web service and try again.')
                from .main import create_app
                config = uvicorn.Config(create_app(self.runtime, host=False), access_log=False, log_level='warning', proxy_headers=False, timeout_graceful_shutdown=5)
                self.server = uvicorn.Server(config)
                self.thread = threading.Thread(target=self.server.run, kwargs={'sockets': [listener]}, daemon=True)
                self.thread.start()
                for _ in range(100):
                    if self.server.started:
                        break
                    if not self.thread.is_alive():
                        raise RuntimeError('The local service could not start.')
                    time.sleep(.05)
                if not self.server.started:
                    raise RuntimeError('The local service took too long to start.')
                name = self.runtime.db.settings()['local_name']
                try:
                    self.zc = Zeroconf(interfaces=[self.ip], ip_version=IPVersion.V4Only)
                    self.info = ServiceInfo('_http._tcp.local.', f'{name}._http._tcp.local.', addresses=[socket.inet_aton(self.ip)], port=self.port,
                                            properties={'path': '/', 'product': 'loc.in'}, server=f'{name}.local.')
                    self.zc.register_service(self.info, allow_name_change=False)
                except Exception:
                    if self.zc:
                        self.zc.close()
                    self.zc, self.info = None, None
                    self.warning = 'Local name advertisement failed or the name is in use. Use the IP address, or choose another name.'
                self.state = 'Running'
            except Exception as exc:
                if self.server:
                    self.server.should_exit = True
                if self.thread:
                    self.thread.join(timeout=7)
                if listener:
                    listener.close()
                self.state = 'Error'
                self.error = str(exc) if isinstance(exc, RuntimeError) else 'The local service could not start. Check your network connection.'

    def stop(self):
        with self.lock:
            if self.server:
                self.server.should_exit = True
            if self.thread:
                self.thread.join(timeout=7)
            if self.zc:
                try:
                    if self.info:
                        self.zc.unregister_service(self.info)
                finally:
                    self.zc.close()
            self.zc = self.info = None
            self.runtime.transfers.stop()
            self.state = 'Stopped'
            self.error = None
