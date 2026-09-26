import sys
from .drive import DriveError


def set_startup(enabled):
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False):
        if enabled:
            raise DriveError('Start with Windows is available in the installed Windows app.', 400)
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run', 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, 'loc.in', 0, winreg.REG_SZ, f'"{sys.executable}" --background')
        else:
            try:
                winreg.DeleteValue(key, 'loc.in')
            except FileNotFoundError:
                pass
