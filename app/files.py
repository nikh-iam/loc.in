"""Shared file API for the loopback host and LAN client."""
import threading
import time
import anyio
from urllib.parse import quote
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from .config import CHUNK, valid_name


class FolderInput(BaseModel):
    parent: str = ''
    name: str = Field(min_length=1, max_length=255)


class UploadInput(FolderInput):
    size: int = Field(ge=0, le=5 * 1024 ** 4)
    mime: str = Field(default='application/octet-stream', max_length=200)


def routes(runtime, host):
    router = APIRouter()
    db, drive, transfers = runtime.db, runtime.drive, runtime.transfers

    def owner(request):
        return 'host' if host else request.state.device

    @router.get('/api/files')
    def listing(parent: str = '', page: str = '', search: str = ''):
        root = db.settings()['folder_id']
        parent = parent or root
        drive.contained(parent, root, folder=True)
        return drive.listing(parent, page or None, search[:200])

    @router.post('/api/folders')
    def create_folder(body: FolderInput):
        parent = body.parent or db.settings()['folder_id']
        drive.contained(parent, db.settings()['folder_id'], folder=True)
        return drive.create_folder(parent, valid_name(body.name))

    @router.post('/api/files/upload')
    def begin_upload(body: UploadInput, request: Request):
        parent = body.parent or db.settings()['folder_id']
        drive.contained(parent, db.settings()['folder_id'], folder=True)
        name = valid_name(body.name)
        if any(ord(c) < 32 for c in body.mime):
            raise HTTPException(400, 'Invalid file type.')
        transfers.reap()
        with transfers.lock:
            key = transfers.begin(name, owner(request), 'upload', body.size)
            item = {'url': None, 'parent': parent, 'offset': 0, 'size': body.size, 'owner': owner(request), 'touched': time.time(), 'lock': threading.Lock()}
            transfers.uploads[key] = item
        try:
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

    @router.put('/api/files/upload/{key}')
    async def upload_chunk(key: str, request: Request, offset: int = 0):
        item = get_upload(key, request)
        if not item['lock'].acquire(blocking=False):
            raise HTTPException(409, 'A chunk is already being uploaded.')
        try:
            if offset != item['offset']:
                raise HTTPException(409, 'Upload offset does not match. Restart the upload.')
            expected = min(CHUNK, item['size'] - offset)
            body = bytearray()
            with anyio.fail_after(120):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > expected:
                        raise HTTPException(413, 'Upload chunk is too large.')
                    body.extend(chunk)
            if len(body) != expected:
                raise HTTPException(400, 'Incomplete upload chunk.')
            await run_in_threadpool(drive.contained, item['parent'], db.settings()['folder_id'], True)
            count, complete = await run_in_threadpool(drive.upload_chunk, item['url'], bytes(body), offset, item['size'])
            if count != offset + len(body) or (complete and count != item['size']):
                raise HTTPException(502, 'Google Drive did not acknowledge the complete chunk. Please restart the upload.')
            item['offset'], item['touched'] = count, time.time()
            transfers.progress(key, count)
            if complete:
                transfers.finish(key)
            return {'transferred': count, 'completed': complete}
        except TimeoutError:
            transfers.finish(key, 'Failed', 'Upload timed out. Please retry the file.')
            raise HTTPException(408, 'Upload chunk timed out. Please retry the file.')
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
    def download(file_id: str, request: Request):
        metadata = drive.contained(file_id, db.settings()['folder_id'])
        with transfers.lock:
            key = transfers.begin(metadata['name'], owner(request), 'download', int(metadata.get('size', 0)))
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
