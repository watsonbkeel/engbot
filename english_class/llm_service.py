"""Student model selection and explicitly authorized platform fallback."""
from __future__ import annotations

import asyncio
import json
import re
import time

from .diagnostics import record, student_tag
from .providers import ProviderError


def error_code(exc: ProviderError) -> str:
    value = exc.code
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', value) else 'ProviderError'


def safe_error(exc: Exception, *keys: str) -> str:
    value = str(exc) or '请求超时'
    for key in keys:
        if key:
            value = value.replace(key, '[已隐藏]')
    return ' '.join(value.split())[:200]


class ModelService:
    def __init__(self, store, providers):
        self.store = store
        self.providers = providers

    async def chat(self, sid, messages, json_output, timeout=45):
        started = time.monotonic()
        own = self.store.llm(sid)
        provider = 'student' if own else 'platform'
        fallback_used, fallback_code, reason = False, None, ''
        result, code = 'error', None
        try:
            # The student attempt and optional platform attempt share one deadline.
            async with asyncio.timeout(timeout):
                if own:
                    try:
                        content = await self.providers.chat(messages, json_output,
                            llm={k: own[k] for k in ('base_url', 'model', 'api_key', 'thinking')}, timeout=timeout)
                        if json_output:
                            try:
                                valid = isinstance(json.loads(content), dict)
                            except (TypeError, ValueError):
                                valid = False
                            if not valid:
                                raise ProviderError('自带模型没有按要求返回 JSON 对象', code='MalformedResponse')
                        self.store.mark_llm(sid, 'ok')
                        result = 'ok'
                        return {'content': content, 'provider': 'student', 'fallback_used': False}
                    except ProviderError as exc:
                        reason = safe_error(exc, own['api_key'], getattr(self.providers, 'llm_key', ''))
                        fallback_code = error_code(exc)
                        if not own.get('allow_platform_fallback', False):
                            self.store.mark_llm(sid, 'error', reason)
                            raise ProviderError('自己的模型暂不可用，未启用平台回退。' + reason,
                                                code='CustomModelUnavailable') from exc
                        fallback_used = True
                        self.store.mark_llm(sid, 'fallback', reason)
                provider = 'platform'
                try:
                    content = await self.providers.chat(messages, json_output, timeout=timeout)
                except ProviderError as exc:
                    if own:
                        self.store.mark_llm(sid, 'error', '自己的模型与平台模型均未完成请求；' + reason)
                    raise
                result = 'ok'
                response = {'content': content, 'provider': 'platform', 'fallback_used': fallback_used}
                if fallback_used:
                    response.update(fallback_code=fallback_code, fallback_reason=reason)
                return response
        except TimeoutError as exc:
            code = 'Timeout'
            if own:
                self.store.mark_llm(sid, 'error', '模型请求超过总等待时限，请重试')
            raise ProviderError('模型请求超过总等待时限，请重试', code=code) from exc
        except ProviderError as exc:
            code = error_code(exc)
            raise
        except BaseException:
            code = 'Cancelled' if asyncio.current_task() and asyncio.current_task().cancelling() else 'InternalError'
            raise
        finally:
            record('model_request', started=started, student=student_tag(sid), provider=provider,
                   fallback_used=fallback_used, fallback_code=fallback_code, result=result, error_code=code)
