import json
import pytest
from app.drive import Drive


def desktop_config():
    return {'installed': {'client_id': 'test-client.apps.googleusercontent.com', 'client_secret': 'test-only-not-real',
                          'auth_uri': 'https://accounts.google.com/o/oauth2/auth', 'token_uri': 'https://oauth2.googleapis.com/token',
                          'redirect_uris': ['http://localhost']}}


def test_host_import_and_configured_status(host, runtime):
    runtime.drive.credentials = None
    assert host.get('/api/status').json()['oauth_configured'] is False
    result = host.post('/api/auth/config', json=desktop_config())
    assert result.status_code == 200
    assert result.json() == {'configured': True}
    assert host.get('/api/status').json()['oauth_configured'] is True
    assert 'test-only-not-real' not in host.get('/api/status').text
    assert 'client_secret' not in host.get('/api/settings').text


def test_lan_cannot_import_config(lan):
    assert lan.post('/api/auth/config', json=desktop_config()).status_code == 404


def test_import_requires_host_authentication(host, runtime):
    host.headers.pop('X-Host-Token')
    assert host.post('/api/auth/config', json=desktop_config()).status_code == 401


@pytest.mark.parametrize('config', [{'web': {}}, {'type': 'service_account'}, [], {}, {'installed': {'client_id': 'bad'}}])
def test_invalid_configuration_rejected(host, runtime, config):
    runtime.drive.credentials = None
    assert host.post('/api/auth/config', json=config).status_code == 400


def test_malformed_and_oversized_configuration(host, runtime):
    runtime.drive.credentials = None
    assert host.post('/api/auth/config', content=b'not-json').status_code == 400
    assert host.post('/api/auth/config', content=b'x' * 16385).status_code == 413


def test_configuration_cannot_redirect_credentials():
    config = desktop_config()
    config['installed']['token_uri'] = 'https://attacker.invalid/token'
    with pytest.raises(ValueError, match='Google authorization endpoints'):
        Drive.validate_oauth_config(config)


def test_imported_configuration_uses_vault_and_survives_restart(monkeypatch):
    vault = {}
    monkeypatch.setattr('app.drive.keyring.get_password', lambda service, account: vault.get((service, account)))
    monkeypatch.setattr('app.drive.keyring.set_password', lambda service, account, value: vault.__setitem__((service, account), value))
    drive = Drive()
    drive.import_oauth_config(desktop_config())
    assert ('loc.in', 'google-client') in vault
    restarted = Drive()
    assert restarted.oauth_ready()
    assert restarted.oauth_config()['installed']['client_id'] == 'test-client.apps.googleusercontent.com'


def test_custom_dns_hostname_is_allowed(lan):
    r = lan.get('/api/status', headers={'Host': 'locin.loc.in'})
    assert r.status_code == 200
    assert r.json()['address'] == 'http://locin.local'
    assert lan.get('/api/status', headers={'Host': 'another.loc.in'}).status_code == 403
    assert lan.get('/api/status', headers={'Host': 'locin.local'}).status_code == 200


def test_local_addresses_include_actual_port(host, runtime):
    runtime.db.save({'local_name': 'vault'})
    runtime.gateway.ip = '192.168.10.2'
    runtime.gateway.port = 8000
    data = host.get('/api/status').json()
    assert data['address'] == 'http://vault.local:8000'
    assert data['fallback'] == 'http://192.168.10.2:8000'
    assert data['custom_address'] == 'http://vault.loc.in:8000'
