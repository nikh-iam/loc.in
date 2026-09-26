"""Initialize streams before third-party imports in a Windows GUI executable."""
import os
import sys

if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

# A smoke run has no UI. Preserve startup tracebacks in its explicitly chosen
# isolated data directory so packaging failures cannot become invisible dialogs.
if '--smoke-test' in sys.argv and os.environ.get('LOCIN_DATA_DIR'):
    import pathlib
    import traceback
    directory = pathlib.Path(os.environ['LOCIN_DATA_DIR'])
    directory.mkdir(parents=True, exist_ok=True)
    stream = open(directory / 'smoke.log', 'w', encoding='utf-8')
    sys.stdout = sys.stderr = stream
    def smoke_exception(exc_type, value, tb):
        traceback.print_exception(exc_type, value, tb, file=stream)
        stream.flush()
    sys.excepthook = smoke_exception
