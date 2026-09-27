import socket


def test_domain_uses_configured_name(host, runtime, monkeypatch):
    runtime.db.save({'local_name': 'home'})
    monkeypatch.setattr('app.main.local_interface', lambda: ('192.168.1.33', '192.168.1.0/24'))
    def resolve(name, port, family):
        assert name == 'home.local'
        assert family == socket.AF_INET
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.168.1.33', 0))]
    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    result = host.post('/api/network/check').json()
    assert result['matches']
    assert result['domain'] == 'home.local'


def test_missing_domain_gives_actual_mapping(host, runtime, monkeypatch):
    monkeypatch.setattr('app.main.local_interface', lambda: ('192.168.1.33', '192.168.1.0/24'))
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args: [])
    result = host.post('/api/network/check').json()
    assert not result['matches']
    assert 'locin.local' in result['message'] and 'IP address' in result['message']


def test_domain_check_not_on_lan(lan):
    assert lan.post('/api/network/check').status_code == 404


def test_domain_check_without_network(host, monkeypatch):
    def unavailable():
        raise RuntimeError('Connect to Wi-Fi first.')
    monkeypatch.setattr('app.main.local_interface', unavailable)
    result = host.post('/api/network/check').json()
    assert not result['matches']
    assert result['message'] == 'Connect to Wi-Fi first.'


def test_qr_requires_running_service(host, runtime):
    assert host.get('/api/network/qr').status_code == 409
    runtime.gateway.ip = '192.168.10.2'
    runtime.gateway.state = 'Running'
    response = host.get('/api/network/qr')
    assert response.status_code == 200
    assert response.headers['content-type'] == 'image/png'
    assert response.content.startswith(b'\x89PNG')


def test_qr_not_exposed_on_lan(lan):
    assert lan.get('/api/network/qr').status_code == 404
