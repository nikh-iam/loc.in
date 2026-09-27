"""Shared file API for the loopback host and LAN client."""
import threading
import time
from functools import wraps
import anyio
from urllib.parse import quote
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from .config import CHUNK, valid_name
from .drive import DriveError
from starlette.requests import ClientDisconnect


class FolderInput(BaseModel):
    parent: str = ''
    name: str = Field(min_length=1, max_length=255)


class UploadInput(FolderInput):
    size: int = Field(ge=0, le=5 * 1024 ** 4)
    mime: str = Field(default='application/octet-stream', max_length=200)


def routes(runtime, host):
    router = APIRouter()
    db, transfers = runtime.db, runtime.transfers

    def storage_operation(function):
        @wraps(function)
        def locked(*args, **kwargs):
            with runtime.settings_lock:
                return function(*args, **kwargs)
        return locked

    def owner(request):
        return 'host' if host else request.state.device

    @router.get('/api/files')
    @storage_operation
    def listing(parent: str = '', page: str = '', search: str = ''):
        drive, root = runtime.storage, runtime.storage_root
        parent = parent or root
        drive.contained(parent, root, folder=True)
        return drive.listing(parent, page or None, search[:200])

    @router.post('/api/folders')
    @storage_operation
    def create_folder(body: FolderInput):
        drive, root = runtime.storage, runtime.storage_root
        parent = body.parent or root
        drive.contained(parent, root, folder=True)
        return drive.create_folder(parent, valid_name(body.name))

    @router.post('/api/files/upload')
    @storage_operation
    def begin_upload(body: UploadInput, request: Request):
        drive, root = runtime.storage, runtime.storage_root
        parent = body.parent or root
        drive.contained(parent, root, folder=True)
        name = valid_name(body.name)
        if any(ord(c) < 32 for c in body.mime):
            raise HTTPException(400, 'Invalid file type.')
        transfers.reap()
        with transfers.lock:
            key = transfers.begin(name, owner(request), 'upload', body.size)
            item = {'url': None, 'parent': parent, 'root': root, 'storage': drive,
                    'cleanup': getattr(drive, 'cancel_upload', None), 'offset': 0, 'size': body.size,
                    'owner': owner(request), 'touched': time.time(), 'lock': threading.Lock()}
            transfers.uploads[key] = item
        try:
            with transfers.lock:
                if key not in transfers.uploads:
                    raise HTTPException(409, 'Upload cancelled before it started.')
                item['url'] = drive.upload_session(parent, name, body.size, body.mime)
            return {'id': key, 'chunk_size': CHUNK}
        except Exception:
            transfers.finish(key, 'Failed', 'Could not start upload.')
            raise

    def get_upload(key, request):
        item = transfers.uploads.get(key)
        if not item or item['owner'] != owner(request):
            raise HTTPException(404, 'Upload not found.')
        return item

    def synchronize(key, item):
        if item.get('needs_sync'):
            count, complete = item['storage'].upload_status(item['url'], item['size'])
            if not item['offset'] <= count <= item['size'] or (complete and count != item['size']):
                raise HTTPException(502, 'Storage returned an invalid upload offset.')
            item['offset'], item['needs_sync'] = count, count == item['size'] and not complete
            transfers.progress(key, count)
            if complete:
                transfers.finish(key)
            return complete
        return False

    @router.get('/api/files/upload/{key}')
    def upload_status(key: str, request: Request):
        if key not in transfers.uploads:
            with db.connect() as connection:
                row = connection.execute('SELECT total FROM transfers WHERE id=? AND device=? AND direction=? AND status=?',
                                         (key, owner(request), 'upload', 'Completed')).fetchone()
            if row:
                return {'transferred': row['total'], 'completed': True, 'chunk_size': CHUNK}
        item = get_upload(key, request)
        if not item['lock'].acquire(blocking=False):
            raise HTTPException(409, 'A chunk is still processing. Retry shortly.')
        try:
            item['storage'].contained(item['parent'], item['root'], True)
            complete = synchronize(key, item)
            item['touched'] = time.time()
            return {'transferred': item['offset'], 'completed': complete, 'chunk_size': CHUNK}
        except (DriveError, HTTPException) as exc:
            status = exc.status if isinstance(exc, DriveError) else exc.status_code
            if status < 500 and status not in (408, 409, 429):
                transfers.finish(key, 'Failed', 'Upload session is no longer available.')
            raise
        finally:
            item['lock'].release()

    @router.put('/api/files/upload/{key}')
    async def upload_chunk(key: str, request: Request, offset: int = 0):
        item = get_upload(key, request)
        if not item['lock'].acquire(blocking=False):
            raise HTTPException(409, 'A chunk is already being uploaded.')
        try:
            await run_in_threadpool(item['storage'].contained, item['parent'], item['root'], True)
            if await run_in_threadpool(synchronize, key, item):
                return {'transferred': item['size'], 'completed': True}
            if offset != item['offset']:
                raise HTTPException(409, 'Upload offset changed. Check upload status and resume.')
            expected = min(CHUNK, item['size'] - offset)
            body = bytearray()
            with anyio.fail_after(120):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > expected:
                        raise HTTPException(413, 'Upload chunk is too large.')
                    body.extend(chunk)
            if len(body) != expected:
                raise HTTPException(400, 'Incomplete upload chunk.')
            drive = item['storage']
            item['needs_sync'] = True
            count, complete = await run_in_threadpool(drive.upload_chunk, item['url'], bytes(body), offset, item['size'])
            if not offset <= count <= offset + len(body) or (complete and count != item['size']):
                raise HTTPException(502, 'Storage did not acknowledge the complete chunk. Please restart the upload.')
            item['needs_sync'] = count == item['size'] and not complete
            item['offset'], item['touched'] = count, time.time()
            transfers.progress(key, count)
            if complete:
                transfers.finish(key)
            return {'transferred': count, 'completed': complete}
        except TimeoutError:
            raise HTTPException(408, 'Upload chunk timed out. Resume to retry this chunk.')
        except ClientDisconnect:
            raise HTTPException(408, 'Connection interrupted. Resume this upload.')
        except (DriveError, HTTPException) as exc:
            status = exc.status if isinstance(exc, DriveError) else exc.status_code
            if status not in (408, 409, 429) and status < 500:
                transfers.finish(key, 'Failed', 'Upload cannot continue. Check storage and retry.')
            raise
        except BaseException:
            transfers.finish(key, 'Failed', 'Upload interrupted. Please retry the file.')
            raise
        finally:
            item['lock'].release()

    @router.delete('/api/files/upload/{key}')
    def cancel_upload(key: str, request: Request):
        item = get_upload(key, request)
        if not item['lock'].acquire(blocking=False):
            raise HTTPException(409, 'Wait for the current chunk to finish, then cancel.')
        try:
            transfers.finish(key, 'Cancelled')
        finally:
            item['lock'].release()
        return {'ok': True}

    @router.get('/api/files/{file_id}/download')
    @storage_operation
    def download(file_id: str, request: Request):
        drive = runtime.storage
        metadata = drive.contained(file_id, runtime.storage_root)
        with transfers.lock:
            key = transfers.begin(metadata['name'], owner(request), 'download', int(metadata.get('size') or 0))
        try:
            client, response, filename, mime = drive.download(metadata)
        except Exception:
            transfers.finish(key, 'Failed', 'Could not start download.')
            raise

        def chunks():
            count = 0
            try:
                for chunk in response.iter_bytes(CHUNK):
                    count += len(chunk)
                    transfers.progress(key, count)
                    yield chunk
                transfers.finish(key)
            except GeneratorExit:
                transfers.finish(key, 'Cancelled')
                raise
            except Exception:
                transfers.finish(key, 'Failed', 'Download interrupted. Please retry the file.')
                raise
            finally:
                response.close()
                client.close()

        iterator = chunks()

        def cleanup():
            # Also runs if the browser leaves before the iterator's first next().
            iterator.close()
            response.close()
            client.close()
            if key in transfers.downloads:
                transfers.finish(key, 'Cancelled')

        class DownloadResponse(StreamingResponse):
            async def __call__(self, scope, receive, send):
                try:
                    await super().__call__(scope, receive, send)
                finally:
                    with anyio.CancelScope(shield=True):
                        await run_in_threadpool(cleanup)

        headers = {'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename, safe=''), 'Cache-Control': 'no-store'}
        length = response.headers.get('content-length')
        if length and length.isdigit():
            headers['Content-Length'] = length
        return DownloadResponse(iterator, media_type='application/octet-stream', headers=headers)

    @router.get('/api/transfers')
    def transfer_list(request: Request):
        transfers.reap()
        return {'transfers': transfers.list(None if host else owner(request))}

    return router
