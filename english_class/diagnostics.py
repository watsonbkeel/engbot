"""Request correlation without logging credentials, audio, or learner content."""
from __future__ import annotations

from contextvars import ContextVar
import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid

from starlette.responses import JSONResponse

REQUEST_ID = ContextVar('english_request_id', default='')
LOG = logging.getLogger('english-class.requests')
_STUDENT_SALT = secrets.token_bytes(32)


def student_tag(student_id: str) -> str:
    # This per-process pseudonym is useful within one run, not a student directory.
    return hmac.new(_STUDENT_SALT, student_id.encode(), hashlib.sha256).hexdigest()[:16]


def record(event: str, *, started: float, **fields) -> None:
    # Callers provide only bounded categorical/numeric fields. Never pass bodies,
    # headers, query strings, URLs, exception text, or recognized learner text.
    LOG.info(json.dumps({'event': event, 'request_id': REQUEST_ID.get(),
                         'latency_ms': round((time.monotonic() - started) * 1000, 2),
                         **fields}, ensure_ascii=False, separators=(',', ':')))


class RequestDiagnostics:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        request_id = uuid.uuid4().hex
        token = REQUEST_ID.set(request_id)
        state = scope.setdefault('state', {})
        state['request_id'] = request_id
        started = time.monotonic()
        status, response_started = 500, False

        async def traced_send(message):
            nonlocal status, response_started
            if message['type'] == 'http.response.start':
                response_started = True
                status = message['status']
                headers = [(k, v) for k, v in message.get('headers', []) if k.lower() != b'x-request-id']
                message = {**message, 'headers': [*headers, (b'x-request-id', request_id.encode())]}
            await send(message)

        try:
            await self.app(scope, receive, traced_send)
        except Exception as exc:
            state['error_code'] = 'InternalError'
            state['exception_type'] = type(exc).__name__
            if response_started:
                raise
            response = JSONResponse({'detail': '服务暂时无法完成请求，请稍后重试并提供请求编号',
                                     'error_code': 'InternalError', 'request_id': request_id}, status_code=500)
            await response(scope, receive, traced_send)
        finally:
            route = getattr(scope.get('route'), 'path', 'unmatched')
            record('http_request', started=started, route=route, method=scope['method'], status=status,
                   student=state.get('student_tag'), result='ok' if status < 400 else 'error',
                   error_code=state.get('error_code'), exception_type=state.get('exception_type'))
            REQUEST_ID.reset(token)
