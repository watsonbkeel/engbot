"""One student, one process, one port. No shared global class conversation."""
from __future__ import annotations
import asyncio
import copy
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException, Depends, Query, Request
from fastapi.responses import Response
from .client import PublicClient, ServiceError
from . import __version__
from .engine import Tutor, learner_stage, command
from .models import TurnInput, SpeechInput, ChatTurnInput
from .turn_recovery import TurnRecovery, RecoverableIO, fingerprint

LOG=logging.getLogger('english-class.brain')
HEARTBEAT_SECONDS=5.0
HEARTBEAT_THROTTLE=3.0


def create_brain(io,edge_token:str,student_prompt:str='',practice_size:int=3,state_path=None):
    if len(edge_token)<16: raise ValueError('EDGE_TOKEN须为至少16位随机凭证')
    recovery_path=Path(state_path).with_name('turn-recovery.json') if state_path else None
    recovery=TurnRecovery(recovery_path)
    tutor=Tutor(RecoverableIO(io,recovery),student_prompt=student_prompt,practice_size=practice_size,state_path=state_path)
    tutor.defer_resume_changes=True
    if recovery.data['state']:
        tutor.restore_state(recovery.data['state'])
        if not recovery.pending: tutor.commit_resume_changes()
    seen={False:float('-inf'),True:float('-inf')}
    heartbeat_lock=asyncio.Lock()

    async def heartbeat(pi=False):
        if not hasattr(io,'heartbeat'): return
        async with heartbeat_lock:
            now=time.monotonic()
            if now-seen[pi]<HEARTBEAT_THROTTLE: return
            seen[pi]=now
            try:
                async with asyncio.timeout(2): await io.heartbeat(pi=pi)
            except (ServiceError,TimeoutError,ValueError):
                LOG.warning('heartbeat unavailable pi=%d',int(pi))

    async def heartbeat_loop():
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await heartbeat(pi=False)
            # Cleanup may wait for the next interval; heartbeats must never wait
            # behind a slow model call holding the lesson lock.
            if not lock.locked():
                async with lock:
                    try: maintain_recovery()
                    except ServiceError: LOG.warning('temporary recovery cleanup unavailable')

    @asynccontextmanager
    async def lifespan(app):
        task=None
        try:
            await heartbeat(pi=False)
            task=asyncio.create_task(heartbeat_loop(),name='brain-heartbeat')
            yield
        finally:
            try:
                if task is not None:
                    task.cancel()
                    try: await task
                    except asyncio.CancelledError: pass
            finally:
                # Close the pool on the same loop, after its last heartbeat.
                # Test/local IO implementations need not own HTTP resources.
                close=getattr(io,'aclose',None)
                if close is not None: await close()

    app=FastAPI(title='Student English brain',version=__version__,docs_url=None,redoc_url=None,lifespan=lifespan)
    app.state.tutor=tutor
    app.state.recovery=recovery
    lock=asyncio.Lock()
    chat_lock=asyncio.Lock()
    chat_state={'session_id':None,'history':[],'cache':{}}

    async def chat_turn(body:ChatTurnInput):
        if body.action=='stop':
            chat_state['session_id']=body.session_id; chat_state['history']=[]; chat_state['cache']={}
            return {'active':False,'phase':'chat','segments':[],'request_id':body.request_id,'session_id':body.session_id}
        cached=chat_state['cache'].get(body.request_id)
        if cached is not None:
            return copy.deepcopy(cached)
        async with chat_lock:
            cached=chat_state['cache'].get(body.request_id)
            if cached is not None: return copy.deepcopy(cached)
            if chat_state['session_id']!=body.session_id:
                chat_state['session_id']=body.session_id; chat_state['history']=[]; chat_state['cache']={}
            if body.action=='enter':
                result={'active':True,'phase':'chat','segments':[{'text':'我在，你想聊什么？','language':'zh'}],
                        'request_id':body.request_id,'session_id':body.session_id}
            else:
                text=body.text.strip()
                if not text: raise HTTPException(422,'聊天内容不能为空')
                messages=[{'role':'system','content':'你是小陈同学，面向中国儿童进行友好、简短的中文聊天。每次最多回答2句、45字；不知道就直说，不编造实时事实，不输出网址和敏感内容。'}]
                messages.extend(chat_state['history'][-6:])
                messages.append({'role':'user','content':text})
                try: answer=await io.chat(messages,json_output=False)
                except ServiceError as exc: raise HTTPException(503,'普通聊天模型暂时不可用，请稍后再试') from exc
                answer=str(answer).strip()[:240]
                if not answer: raise HTTPException(503,'普通聊天没有生成有效回答')
                chat_state['history']=(chat_state['history']+[{'role':'user','content':text},{'role':'assistant','content':answer}])[-6:]
                result={'active':True,'phase':'chat','segments':[{'text':answer,'language':'zh'}],
                        'request_id':body.request_id,'session_id':body.session_id}
            chat_state['cache'][body.request_id]=copy.deepcopy(result)
            if len(chat_state['cache'])>32: chat_state['cache'].pop(next(iter(chat_state['cache'])))
            return result

    def auth(authorization:str|None=Header(default=None)):
        expected='Bearer '+edge_token
        if authorization is None or not hmac.compare_digest(authorization,expected):
            raise HTTPException(401,'树莓派脑端凭证无效')

    @app.get('/health')
    def health(): return {'ok':True,'service':'student-brain','version':__version__}

    @app.post('/chat/turn',dependencies=[Depends(auth)])
    async def chat(body:ChatTurnInput):
        await heartbeat(pi=True)
        return await chat_turn(body)

    def maintain_recovery():
        if not recovery.pending and getattr(tutor,'_resume_change',None)=={'action':'clear'}:
            tutor.commit_resume_changes()
            # Keep the durable clear intent until the old checkpoint is gone;
            # expiry must not remove the guard and resurrect that old question.
            if tutor._resume_change: return
        if recovery.expired():
            if recovery.pending: tutor.restore_state(recovery.pending['before'])
            tutor.save_resume()
            tutor.commit_resume_changes()
            empty=Tutor(tutor.io,student_prompt=student_prompt,practice_size=practice_size,state_path=state_path,
                        clock=tutor.clock,wall=tutor.wall)
            tutor.restore_state(empty.export_state())
            recovery.reset()
        elif recovery.prune():
            recovery.save()

    def question_signature():
        return (tutor.session_id,tutor.phase,tutor.index,tutor.dialog_count,
                getattr(tutor,'help_stage',''),getattr(tutor,'help_turn',0),
                getattr(tutor,'scene_opening_pending',False),getattr(tutor,'repeat_tries',0),
                getattr(tutor,'scene_opening_tries',0))

    def require_current(session_id,question_id,*,audio=False):
        if ((session_id is not None and (session_id!=tutor.session_id or question_id!=recovery.question_id))
                or (audio and tutor.phase in ('idle','done','paused'))):
            raise HTTPException(409,{'code':'stale_question','message':'这段回答属于旧题，未识别或写入；请听当前题目再回答',
                                     'current':{**tutor.result([],remember=False),'question_id':recovery.question_id}})

    async def close_upgraded_turn(body,digest):
        pending=recovery.pending
        original_key=pending['request_id']
        before=copy.deepcopy(pending['before'])
        try:
            if body.request_id==original_key:
                await recovery.settle_records(io)
            # Explicit stop can close even while a public write is unavailable.
            # It abandons unconfirmed intents but never erases committed progress.
            tutor.restore_state(before)
            tutor.finish(completed=True)  # Only schedules checkpoint deletion; no learning writes.
            tutor.history=[]
            message=tutor.message('系统已升级，本轮练习已结束，已确认的学习记录已保留，请重新开始。',
                                  'The system has been upgraded. This practice has ended. '
                                  'Confirmed learning records have been kept. Please start again.')
            question_id=uuid.uuid4().hex
            original={**tutor.result(message),'request_id':original_key,'question_id':question_id}
            reply={**original,'request_id':body.request_id}
            extra=(body.request_id,digest,reply) if body.request_id!=original_key else None
            recovery.complete(original,tutor,question_id,extra_reply=extra)
        except BaseException as exc:
            tutor.restore_state(before)
            if isinstance(exc,ValueError):
                raise ServiceError('升级前的学习记录暂时无法确认；可重试原请求或明确结束练习') from exc
            raise
        tutor.commit_resume_changes()  # Only after closure and replay results are durable.
        return reply

    async def run_turn_locked(body:TurnInput,digest=None,wav=None):
        digest=digest or fingerprint(body.model_dump())
        key=body.request_id
        # Match Tutor's reliable text-control handling for admission/cleanup,
        # while preserving the exact original body and its replay fingerprint.
        effective_action=body.action
        if (effective_action=='answer' and not body.unclear and body.text.strip()
                and (body.confidence is None or body.confidence>=0.65)):
            effective_action=command(body.text) or 'answer'
        try:
            maintain_recovery()
            cached=recovery.lookup(key,digest)
            if cached is not None: return cached
            if recovery.needs_upgrade_close:
                if recovery.pending['request_id']!=key and effective_action!='stop':
                    raise ValueError('上一回合尚未确认；请先用原请求编号恢复，或明确结束练习')
                return await close_upgraded_turn(body,digest)
            if effective_action=='start' and getattr(tutor,'_resume_change',None)=={'action':'clear'}:
                raise ServiceError('旧课堂断点暂时无法清理；请检查状态目录后重新开始')
            if recovery.pending and recovery.pending['request_id']!=key and effective_action=='stop':
                recovery.abandon(tutor)
            if not recovery.pending:
                require_current(body.session_id,body.question_id,audio=wav is not None)
            if wav is not None:
                # Invalid audio is a permanent input error, not a recoverable
                # provider failure. Never journal it as an unconfirmed turn.
                from .providers import validate_wav
                try: validate_wav(wav)
                except ValueError as exc: raise HTTPException(422,str(exc)) from exc
            recovery.begin(key,digest,tutor)
        except ValueError as exc: raise HTTPException(409,str(exc)) from exc
        except ServiceError as exc: raise HTTPException(503,str(exc)) from exc
        before=question_signature()
        try:
            asr=None
            if wav is not None:
                asr=await tutor.io.transcribe(wav,tutor.last_expected)
                body=body.model_copy(update={'text':asr['text'],'confidence':asr.get('confidence'),
                                             'unclear':asr.get('unclear',False)})
                LOG.info('asr class_request=%s provider=%s fallback_reason=%s asr_request=%s unclear=%d',key,
                         asr.get('provider','-'),asr.get('fallback_reason') or '-',asr.get('request_id') or '-',int(bool(asr.get('unclear'))))
            reply=await tutor.turn(body.text,action=body.action,request_id=key,confidence=body.confidence,unclear=body.unclear)
            question_id=uuid.uuid4().hex if question_signature()!=before else recovery.question_id
            reply={**reply,'request_id':key,'question_id':question_id}
            if asr is not None:
                reply.update(recognized_text=asr['text'],asr_provider=asr.get('provider'))
            recovery.complete(reply,tutor,question_id)
        except BaseException as exc:
            recovery.failed(tutor)
            if isinstance(exc,(ServiceError,ValueError)):
                raise HTTPException(503,str(exc)) from exc
            raise
        # Deleting/replacing the vocabulary resume checkpoint is safe only after
        # the next question and the reply to replay have both been committed.
        tutor.commit_resume_changes()
        return reply

    async def run_turn(body:TurnInput):
        await heartbeat(pi=True)
        async with lock:
            return await run_turn_locked(body)

    @app.post('/voice/turn',dependencies=[Depends(auth)])
    async def turn(body:TurnInput): return await run_turn(body)

    @app.post('/voice/audio',dependencies=[Depends(auth)])
    async def audio(request:Request,request_id:str=Query(min_length=8,max_length=128),
                    session_id:str=Query(min_length=1,max_length=64),question_id:str=Query(min_length=1,max_length=64)):
        chunks=[];size=0
        async for chunk in request.stream():
            size+=len(chunk)
            if size>1_000_000: raise HTTPException(413,'每轮录音不得超过30秒')
            chunks.append(chunk)
        wav=b''.join(chunks)
        digest=fingerprint(['audio',session_id,question_id,hashlib.sha256(wav).hexdigest()])
        await heartbeat(pi=True)
        async with lock:
            body=TurnInput(request_id=request_id,session_id=session_id,question_id=question_id)
            return await run_turn_locked(body,digest,wav)

    @app.post('/voice/speech',dependencies=[Depends(auth)])
    async def speech(body:SpeechInput):
        speed=learner_stage(tutor.config.get('grade'))[0].split()[0]
        try: data=await io.speak([x.model_dump() for x in body.segments],body.slow,speed=speed)
        except (ServiceError,ValueError) as exc: raise HTTPException(503,str(exc)) from exc
        return Response(data,media_type='audio/wav',headers={'Cache-Control':'no-store'})

    @app.post('/voice/push',dependencies=[Depends(auth)])
    async def legacy_push(request:Request):
        """Text bridge adapter. Optional trusted-LAN callback uses original /speak API."""
        payload=await request.json()
        if not isinstance(payload,dict) or not isinstance(payload.get('text'),str): raise HTTPException(422,'text is required')
        # Text equality is not an event identity: the same start/pause command can
        # be spoken again. Bridges that retry a delivery should supply its ID.
        from pydantic import ValidationError
        try: body=TurnInput(text=payload['text'],request_id=payload.get('request_id') or 'legacy-'+uuid.uuid4().hex)
        except ValidationError as exc: raise HTTPException(422,'桥接请求编号或文本无效') from exc
        reply=await run_turn(body)
        callback=os.environ.get('AIBOT_BODY_URL','').rstrip('/')
        if callback and reply['segments']:
            import httpx
            headers={}
            if os.environ.get('NOX_API_TOKEN'): headers['Authorization']='Bearer '+os.environ['NOX_API_TOKEN']
            try:
                async with httpx.AsyncClient(timeout=45) as c:
                    r=await c.post(callback+'/speak',headers=headers,json={'text':' '.join(x['text'] for x in reply['segments'])})
                    r.raise_for_status()
            except httpx.HTTPError as exc: raise HTTPException(503,'原aibot播报回调失败；使用课程语音插件可避免反向回调') from exc
        return reply
    return app


def from_env():
    required=('STUDENT_ID','BRAIN_TOKEN','EDGE_TOKEN')
    for key in required:
        if not os.environ.get(key): raise ValueError(f'未配置{key}')
    from . import DEFAULT_PUBLIC_PORT
    io=PublicClient(os.environ.get('PUBLIC_URL',f'http://127.0.0.1:{DEFAULT_PUBLIC_PORT}'),os.environ['STUDENT_ID'],os.environ['BRAIN_TOKEN'])
    prompt_path=Path(os.environ.get('STUDENT_PROMPT_PATH','prompts/student.md'))
    prompt=prompt_path.read_text(encoding='utf-8') if prompt_path.is_file() else ''
    # 断点文件：默认放在 systemd StateDirectory（/var/lib/english-class-brain/<sid>/），未设置则不保存断点。
    state=os.environ.get('RESUME_STATE_PATH') or (os.path.join(os.environ['STATE_DIRECTORY'],'resume.json') if os.environ.get('STATE_DIRECTORY') else None)
    return create_brain(io,os.environ['EDGE_TOKEN'],prompt,int(os.environ.get('PRACTICE_WORDS','3')),state_path=state)
