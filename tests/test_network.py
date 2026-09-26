import time
from types import SimpleNamespace
import pytest
from app import network


@pytest.fixture
def network_stack(monkeypatch):
    stack = SimpleNamespace(busy=set(), listeners=[], registrations=[], removed=[], conflict=False)

    class Listener:
        def __init__(self, *args):
            self.closed = False
            stack.listeners.append(self)

        def bind(self, address):
            self.address = address
            if address[1] in stack.busy:
                raise OSError('Port in use')

        def listen(self, backlog):
            pass

        def setblocking(self, blocking):
            pass

        def close(self):
            self.closed = True

    class Server:
        def __init__(self, config):
            self.started = False
            self.should_exit = False

        def run(self, sockets):
            self.started = True
            while not self.should_exit:
                time.sleep(.001)
            for item in sockets:
                item.close()

    class Discovery:
        def __init__(self, **kwargs):
            stack.discovery_options = kwargs

        def register_service(self, info, **kwargs):
            if stack.conflict:
                raise RuntimeError('Name collision')
            stack.registrations.append(info)

        def unregister_service(self, info):
            stack.removed.append(info)

        def close(self):
            pass

    monkeypatch.setattr(network, 'local_interface', lambda: ('192.168.10.2', '192.168.10.0/24'))
    monkeypatch.setattr(network.socket, 'socket', Listener)
    monkeypatch.setattr(network.uvicorn, 'Server', Server)
    monkeypatch.setattr(network, 'Zeroconf', Discovery)
    return stack


def test_service_binds_specific_interface_and_announces(runtime, network_stack):
    runtime.db.save({'local_name': 'vault'})
    runtime.gateway.start()
    try:
        assert runtime.gateway.state == 'Running'
        assert network_stack.listeners[0].address == ('192.168.10.2', 80)
        assert runtime.gateway.address() == 'http://vault.loc.in'
        info = network_stack.registrations[0]
        assert info.server == 'vault.local.'
        assert info.port == 80
        assert info.parsed_addresses() == ['192.168.10.2']
        assert network_stack.discovery_options['interfaces'] == ['192.168.10.2']
    finally:
        runtime.gateway.stop()
    assert runtime.gateway.state == 'Stopped'
    assert network_stack.removed == network_stack.registrations
    assert network_stack.listeners[0].closed


def test_port_fallback_includes_actual_port(runtime, network_stack):
    network_stack.busy.add(80)
    runtime.gateway.start()
    try:
        assert runtime.gateway.state == 'Running'
        assert runtime.gateway.address() == 'http://locin.loc.in:8000'
        assert network_stack.registrations[0].port == 8000
    finally:
        runtime.gateway.stop()


def test_busy_ports_leave_clear_error(runtime, network_stack):
    network_stack.busy.update({80, 8000})
    runtime.gateway.start()
    assert runtime.gateway.state == 'Error'
    assert 'in use' in runtime.gateway.error
    assert all(item.closed for item in network_stack.listeners)


def test_discovery_failure_keeps_ip_fallback_running(runtime, network_stack):
    network_stack.conflict = True
    runtime.gateway.start()
    try:
        assert runtime.gateway.state == 'Running'
        assert runtime.gateway.ip == '192.168.10.2'
        assert 'IP address' in runtime.gateway.warning
    finally:
        runtime.gateway.stop()


def test_repeated_start_is_idempotent(runtime, network_stack):
    runtime.gateway.start()
    runtime.gateway.start()
    try:
        assert len(network_stack.listeners) == 1
    finally:
        runtime.gateway.stop()


def test_no_network_is_actionable(runtime, monkeypatch):
    def unavailable():
        raise RuntimeError('Connect this computer to Wi-Fi or Ethernet, then try again.')
    monkeypatch.setattr(network, 'local_interface', unavailable)
    runtime.gateway.start()
    assert runtime.gateway.state == 'Error'
    assert 'Wi-Fi or Ethernet' in runtime.gateway.error
