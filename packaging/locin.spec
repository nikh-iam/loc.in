# Build with: python -m PyInstaller packaging/locin.spec
from pathlib import Path
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH).parent
data = [(str(root / 'frontend'), 'frontend')]
if (root / 'oauth-client.json').exists():
    data.append((str(root / 'oauth-client.json'), '.'))
data += collect_data_files('webview')
a = Analysis([str(root / 'run.py')], pathex=[str(root)], binaries=[], datas=data,
             runtime_hooks=[str(root / 'packaging/windowless_runtime.py')],
             hiddenimports=collect_submodules('keyring.backends') + ['uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.h11_impl', 'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan.on', 'webview.platforms.winforms'],
             excludes=['tkinter', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='locin', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=os.environ.get('LOCIN_CONSOLE') == '1',
          icon=str(root / 'packaging/locin.ico') if (root / 'packaging/locin.ico').exists() else None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='locin')
