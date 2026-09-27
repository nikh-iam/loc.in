import pytest
from fastapi.testclient import TestClient
from app.database import Database
from app.main import Runtime, create_app
from .fakes import FakeDrive


@pytest.fixture
def runtime(tmp_path):
    db = Database(tmp_path / 'locin.db')
    db.save({'folder_id': 'shared', 'folder_name': 'loc.in'})
    return Runtime(db=db, drive=FakeDrive())


@pytest.fixture
def host(runtime):
    with TestClient(create_app(runtime), base_url='http://127.0.0.1:4028', client=('127.0.0.1', 50000), headers={'X-Host-Token': runtime.host_token}) as client:
        yield client


@pytest.fixture
def lan(runtime):
    runtime.gateway.ip = '192.168.10.2'
    runtime.gateway.subnet = '192.168.10.0/24'
    runtime.gateway.state = 'Running'
    with TestClient(create_app(runtime, host=False), base_url='http://locin.loc.in', client=('192.168.10.3', 50001), headers={'X-Locin-Request': '1'}) as client:
        yield client
