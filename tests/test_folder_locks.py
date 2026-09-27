from fastapi.testclient import TestClient
from app.main import create_app
from app.locks import FolderLocks


def protect(host, folder='shared', password='my-password'):
    result = host.post('/api/folder-lock', json={'folder_id':folder,'password':password})
    assert result.status_code == 200, result.text


def client(runtime):
    runtime.gateway.ip='192.168.10.2'
    runtime.gateway.subnet='192.168.10.0/24'
    runtime.gateway.state='Running'
    return TestClient(create_app(runtime,host=False),base_url='http://locin.loc.in',client=('192.168.10.3',1234),headers={'X-Locin-Request':'1'})


def test_root_protects_all_operations_and_unlocks(host,runtime):
    protect(host)
    assert host.get('/api/files').status_code == 200
    with client(runtime) as lan:
        assert lan.get('/api/files').status_code == 423
        assert lan.get('/api/files/file1/download').status_code == 423
        assert lan.post('/api/folders',json={'name':'Private'}).status_code == 423
        assert lan.post('/api/files/upload',json={'name':'x','size':1}).status_code == 423
        assert lan.post('/api/folders/unlock',json={'folder_id':'shared','password':'incorrect'}).status_code == 403
        result=lan.post('/api/folders/unlock',json={'folder_id':'shared','password':'my-password'})
        assert result.status_code == 200
        assert 'HttpOnly' in result.headers['set-cookie']
        assert lan.get('/api/files').status_code == 200
        assert lan.get('/api/files/file1/download').status_code == 200
        assert lan.post('/api/folder-lock',json={'remove':True}).status_code == 404


def test_nested_folder_cannot_be_bypassed_and_other_folders_work(host,runtime):
    runtime.drive.items['nested']={'id':'nested','name':'Hidden.txt','parents':['photos'],'mimeType':'text/plain','size':'1'}
    protect(host,'photos')
    with client(runtime) as lan:
        assert lan.get('/api/files').status_code == 200
        assert lan.get('/api/files?parent=photos').status_code == 423
        assert lan.get('/api/files/nested/download').status_code == 423
        assert lan.get('/api/files/file1/download').status_code == 200


def test_password_persists_without_plaintext_and_grant_expires(host,runtime):
    protect(host)
    rows=runtime.folder_locks.records()
    assert 'my-password' not in str(rows)
    runtime.folder_locks=FolderLocks(runtime.db)
    with client(runtime) as lan:
        assert lan.get('/api/files').status_code == 423
        lan.post('/api/folders/unlock',json={'folder_id':'shared','password':'my-password'})
        for grant in runtime.folder_locks.sessions.values():
            grant['expires']=0
        assert lan.get('/api/files').status_code == 423


def test_rate_limit_and_password_validation(host,runtime):
    assert host.post('/api/folder-lock',json={'password':'short'}).status_code == 400
    protect(host)
    with client(runtime) as lan:
        for _ in range(10):
            assert lan.post('/api/folders/unlock',json={'folder_id':'shared','password':'bad'}).status_code == 403
        assert lan.post('/api/folders/unlock',json={'folder_id':'shared','password':'my-password'}).status_code == 429


def test_local_nested_password(host,runtime,tmp_path):
    from .test_local_storage import configure
    folder=configure(host,tmp_path)
    (folder/'Private').mkdir()
    (folder/'Private'/'secret.txt').write_text('secret')
    private=host.get('/api/files').json()['files'][0]['id']
    file_id=host.get('/api/files',params={'parent':private}).json()['files'][0]['id']
    protect(host,private)
    runtime.db.save({'local_name':'locin'})
    with client(runtime) as lan:
        assert lan.get('/api/files/'+file_id+'/download').status_code == 423
        import base64
        alias='local_'+base64.urlsafe_b64encode(b'Private/secret.txt').decode()
        assert lan.get('/api/files/'+alias+'/download').status_code == 423
        import os
        if os.name=='nt':
            alias='local_'+base64.urlsafe_b64encode(b'private/SECRET.TXT').decode()
            assert lan.get('/api/files/'+alias+'/download').status_code == 423
        assert lan.post('/api/folders/unlock',json={'folder_id':private,'password':'my-password'}).status_code == 200
        assert lan.get('/api/files/'+file_id+'/download').content == b'secret'


def test_new_local_setup_has_no_error_or_automatic_folder(host,runtime):
    runtime.db.save({'storage_mode':'local','local_folder':''})
    status=host.get('/api/status').json()
    assert not status['unavailable'] and not status['connected']
    assert status['folder_id']==''


def test_one_domain_persists_between_storage_modes(host):
    assert host.put('/api/settings',json={'storage_mode':'local','local_name':'home'}).status_code==200
    assert host.put('/api/settings',json={'storage_mode':'drive','local_name':'home'}).status_code==200
    assert host.get('/api/status').json()['address']=='http://home.local'


def test_upload_grant_expiry_preserves_resume_session(host,runtime):
    protect(host)
    with client(runtime) as lan:
        lan.post('/api/folders/unlock',json={'folder_id':'shared','password':'my-password'})
        key=lan.post('/api/files/upload',json={'name':'file','size':1}).json()['id']
        for grant in runtime.folder_locks.sessions.values():
            grant['expires']=0
        assert lan.put('/api/files/upload/'+key,content=b'x').status_code==423
        assert key in runtime.transfers.uploads
        lan.post('/api/folders/unlock',json={'folder_id':'shared','password':'my-password'})
        assert lan.put('/api/files/upload/'+key,content=b'x').json()['completed']


def test_cookie_cannot_unlock_other_device(host,runtime):
    protect(host)
    with client(runtime) as lan:
        lan.post('/api/folders/unlock',json={'folder_id':'shared','password':'my-password'})
        token=lan.cookies.get('locin_folders')
        with TestClient(create_app(runtime,host=False),base_url='http://locin.loc.in',client=('192.168.10.9',1234),cookies={'locin_folders':token}) as other:
            assert other.get('/api/files').status_code==423
