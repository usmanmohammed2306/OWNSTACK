"""Bounded ASGI ingress and production authority checks, before route execution."""
import asyncio
import json
import time
from urllib.parse import urlsplit
from ownstack.config import Settings

MAX_REQUEST_BYTES = 65_536


class SecurityBoundary:
    def __init__(self, app):
        self.app = app

    async def reject(self, send, status, message):
        body = json.dumps({'detail': message}).encode()
        await send({'type': 'http.response.start', 'status': status, 'headers': [
            (b'content-type', b'application/json'), (b'cache-control', b'no-store'),
            (b'x-content-type-options', b'nosniff'), (b'content-length', str(len(body)).encode())]})
        await send({'type': 'http.response.body', 'body': body})

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        settings = Settings()
        headers = scope.get('headers', [])
        if settings.environment == 'production':
            if scope.get('path') in {'/docs', '/redoc', '/openapi.json'}:
                return await self.reject(send, 404, 'Not found')
            hosts = [value.decode('latin1').lower() for key, value in headers if key.lower() == b'host']
            expected = urlsplit(settings.public_origin).netloc.lower()
            if hosts != [expected]:
                return await self.reject(send, 400, 'Request host is not permitted')
            # Forwarded headers are interpreted only by the explicitly trusted ASGI server.
            # Reading X-Forwarded-Proto directly here would trust arbitrary clients.
            if scope.get('scheme') != 'https':
                return await self.reject(send, 426, 'HTTPS is required')
        lengths = [value for key, value in headers if key.lower() == b'content-length']
        if len(lengths) > 1 or (lengths and (not lengths[0].isdigit() or len(lengths[0]) > 10)):
            return await self.reject(send, 400, 'Invalid Content-Length')
        if lengths and int(lengths[0]) > MAX_REQUEST_BYTES:
            return await self.reject(send, 413, 'Request body exceeds 64 KiB')
        chunks, total, started = [], 0, time.monotonic()
        while True:
            remaining = min(5, 20 - (time.monotonic() - started))
            if remaining <= 0:
                return await self.reject(send, 408, 'Request body deadline exceeded')
            try:
                message = await asyncio.wait_for(receive(), remaining)
            except TimeoutError:
                return await self.reject(send, 408, 'Request body deadline exceeded')
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            total += len(chunk)
            if total > MAX_REQUEST_BYTES:
                return await self.reject(send, 413, 'Request body exceeds 64 KiB')
            chunks.append(chunk)
            if not message.get('more_body', False):
                break
        if lengths and total != int(lengths[0]):
            return await self.reject(send, 400, 'Content-Length mismatch')
        body, delivered = b''.join(chunks), False
        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return await receive()
        await self.app(scope, bounded_receive, send)
