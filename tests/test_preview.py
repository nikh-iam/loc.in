def test_preview_text_and_cleanup(lan, runtime):
    response = lan.get('/api/files/file1/preview')
    assert response.status_code == 200
    assert response.content == b'Welcome to your local space!'
    assert response.headers['content-type'] == 'application/octet-stream'
    assert runtime.drive.download_closed
    assert not runtime.transfers.downloads


def test_preview_refuses_active_content_and_large_files(lan, runtime):
    runtime.drive.items['file1']['mimeType'] = 'text/html'
    assert lan.get('/api/files/file1/preview').status_code == 415
    runtime.drive.items['file1']['mimeType'] = 'text/plain'
    runtime.drive.items['file1']['size'] = str(11 * 1024 * 1024)
    assert lan.get('/api/files/file1/preview').status_code == 413


def test_preview_enforces_scope_and_password(lan, runtime):
    assert lan.get('/api/files/private-file/preview').status_code == 403
    runtime.folder_locks.configure('shared', 'test-password')
    assert lan.get('/api/files/file1/preview').status_code == 423
