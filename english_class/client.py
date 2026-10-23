"""Student-side client. It carries a scoped classroom token, never provider keys."""
from __future__ import annotations
import asyncio
import httpx

class ServiceError(RuntimeError):
    pass

class PublicClient:
    def __init__(self,base_url:str,student_id:str,token:str):
        self.base_url=base_url.rstrip('/');self.student_id=student_id;self.token=token
        self._client=None;self._loop=None

    def _session(self):
        loop=asyncio.get_running_loop()
        if self._client is not None and self._loop is not loop:
            raise ServiceError('公共服务连接尚未在原事件循环中关闭')
        if self._client is None:
            # Each student owns one pool. Create it inside the serving loop;
            # headers remain per request so credentials cannot cross clients.
            self._client=httpx.AsyncClient(timeout=httpx.Timeout(90,connect=8),
                                           limits=httpx.Limits(max_connections=10,max_keepalive_connections=5,
                                                               keepalive_expiry=30))
            self._loop=loop
        return self._client

    async def aclose(self):
        if self._client is not None:
            if self._loop is not asyncio.get_running_loop():
                raise ServiceError('公共服务连接须在原事件循环中关闭')
            await self._client.aclose()
            self._client=None;self._loop=None

    async def request(self,method:str,path:str,*,params=None,body=None,content=None,event_key=None,raw=False):
        headers={'Authorization':'Bearer '+self.token}
        if content is not None: headers['Content-Type']='audio/wav'
        if event_key: headers['Idempotency-Key']=event_key
        query={'student_id':self.student_id,**(params or {})}
        try:
            response=await self._session().request(method,self.base_url+path,params=query,headers=headers,json=body,content=content)
            if response.status_code>=400:
                try: error=response.json()
                except ValueError: error=None
                detail=error.get('detail') if isinstance(error,dict) else None
                # Validation payloads can contain submitted lesson text. Only
                # the public service's deliberate message is relayed to Pi.
                if not isinstance(detail,str) or not detail.strip(): detail='服务未完成请求'
                raise ServiceError(f'公共服务返回 {response.status_code}：{detail}')
            return response.content if raw else response.json()
        except (httpx.HTTPError,httpx.InvalidURL,ValueError) as exc:
            raise ServiceError('未能连接公共服务；本轮不能宣称已保存或已答对') from exc

    async def config(self): return await self.request('GET','/api/config')
    async def words(self,cfg):
        result=await self.request('GET','/api/words',params={k:cfg[k] for k in ('grade','semester','unit')})
        return result['words']
    async def progress(self): return await self.request('GET','/api/progress')
    async def record(self,word_id,status,unclear,key,evidence=None):
        body={'word_id':word_id,'status':status,'unclear':unclear}
        if evidence is not None: body['evidence']=evidence
        return await self.request('POST','/api/progress',body=body,event_key=key)
    async def record_lesson(self,payload):
        return await self.request('POST','/api/lessons',body=payload)
    async def chat(self,messages,json_output=True):
        return (await self.request('POST','/internal/chat',body={'messages':messages,'json_output':json_output}))['content']
    async def transcribe(self,wav,language):
        return await self.request('POST','/internal/asr',params={'language':language},content=wav)
    async def speak(self,segments,slow=False,speed='middle'):
        return await self.request('POST','/internal/tts',body={'segments':segments,'slow':slow,'speed':speed},raw=True)
    async def heartbeat(self,pi=False):
        return await self.request('POST','/api/status/heartbeat',body={'pi':pi})
