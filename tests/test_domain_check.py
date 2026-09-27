import socket


def test_domain_uses_configured_name(host, runtime, monkeypatch):
    runtime.db.save({'local_name': 'home'})
    runtime.gateway.ip = '192.168.1.33'
    def resolve(name, port, family):
        assert name == 'home.loc.in'
        assert family == socket.AF_INET
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.168.1.33', 0))]
    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    result = host.post('/api/network/check').json()
    assert result['matches']
    assert result['domain'] == 'home.loc.in'


def test_missing_domain_gives_actual_mapping(host, runtime, monkeypatch):
    runtime.gateway.ip = '192.168.1.33'
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args: [])
    result = host.post('/api/network/check').json()
    assert not result['matches']
    assert 'locin.loc.in' in result['message'] and '192.168.1.33' in result['message']


def test_domain_check_not_on_lan(lan):
    assert lan.post('/api/network/check').status_code == 404
