from unittest.mock import Mock
from app.uninstall import cleanup_user_data


def test_cleanup_removes_app_state_but_preserves_shared_files(tmp_path):
    root = tmp_path / 'loc.in'
    root.mkdir()
    for name in ('locin.db', 'locin.db-wal', 'smoke.log'):
        (root/name).write_text('application data')
    (root/'webview').mkdir()
    (root/'webview'/'cache').write_text('cache')
    shared = tmp_path/'Shared'
    shared.mkdir()
    (shared/'photo.jpg').write_bytes(b'keep')
    vault, startup = Mock(), Mock()
    cleanup_user_data(tmp_path, vault, startup)
    assert not root.exists()
    assert (shared/'photo.jpg').read_bytes() == b'keep'
    assert vault.delete_password.call_count == 2
    startup.assert_called_once()


def test_cleanup_never_removes_unknown_user_content(tmp_path):
    root = tmp_path/'loc.in'
    root.mkdir()
    (root/'keep.txt').write_text('user file')
    (root/'locin.db').write_text('db')
    cleanup_user_data(tmp_path, Mock(), Mock())
    assert (root/'keep.txt').read_text() == 'user file'
    assert not (root/'locin.db').exists()


def test_even_a_shared_folder_inside_cache_is_preserved(tmp_path):
    from app.database import Database
    root=tmp_path/'loc.in'
    root.mkdir()
    shared=root/'webview'/'Shared'
    shared.mkdir(parents=True)
    (shared/'keep.txt').write_text('personal')
    db=Database(root/'locin.db')
    db.save({'local_folder':str(shared)})
    cleanup_user_data(tmp_path,Mock(),Mock())
    assert (shared/'keep.txt').read_text()=='personal'
