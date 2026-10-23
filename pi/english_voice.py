#!/usr/bin/env python3
"""aibot course addon: local Chinese wake/control, English audio sent to own brain.

Only this process owns the microphone during course mode. It does not rewrite the
existing nox files. Stop nox-voice explicitly before enabling this service.
"""
from __future__ import annotations
import argparse
import base64
import copy
import hashlib
import io
import json
import logging
import os
import queue
import shlex
import signal
import subprocess
import threading
import time
import uuid
import wave
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from english_class.turn_recovery import RECOVERY_TTL_SECONDS, private_json_write
from .audio import VoiceActivity,find_usb_mic,control_action,split_wake,amplify,WAKE_WORDS

LOG=logging.getLogger('english-edge')
TICK_SECONDS=5
READY_MESSAGE='小陈同学已就绪。说，小陈同学，学英语，开始上课；只说小陈同学，就是普通聊天。'
READY_AUDIO=os.environ.get('READY_AUDIO','/opt/english-class/data/replies/ready.wav')
REPLY_AUDIO_DIR=os.environ.get('REPLY_AUDIO_DIR','/opt/english-class/data/replies')
# 固定话术一律播预置音频：espeak-ng 的中文机械断续，这几种提示每次措辞都一样。
# 改文案必须重新生成对应文件（生成脚本 make_kokoro.py），文件缺失时自动回退 espeak。
MESSAGE_AUDIO={
    '连接暂时有问题。正在确认上一轮，请先等待；也可以说结束练习。':'msg_conn_error.wav',
    '这段录音属于上一题。请说，再说一次，听当前题目后再回答。':'msg_stale_turn.wav',
    '这次请求未被接受。请重新回答当前题目。':'msg_rejected.wav',
    '播报暂时没有完成。请说，再说一次，听当前题目。':'msg_playback_failed.wav',
    '播报暂时没有完成。请说，再说一次，听结束点评。':'msg_playback_failed_final.wav',
    '我在。普通聊天服务尚未连接，请说，小陈同学，学英语，进入英语课堂。':'msg_chat_offline.wav',
}


def read_reply_audio(path):
    """固定话术的预置音频：命中就直接播，不用现场合成。
    espeak-ng 的中文本身机械又断续，启动提示这类每次都一样的句子没必要现生成。"""
    if not path: return None
    try:
        data=Path(path).read_bytes()
    except OSError:
        return None
    return data if len(data)>44 else None


class BrainRequestError(RuntimeError):
    def __init__(self,status,detail):
        # Detail may carry a complete current question (stale_question) or
        # validation input. Keep it for recovery, never in default error logs.
        super().__init__(f'脑端请求失败（HTTP {status}）')
        self.status,self.detail=status,detail


class Chat:
    """只说“小陈同学”时的普通聊天：中文文字交给原机器人的本机 bridge，由原机器人云端回答并用它自己的声音播放。
    不改原机器人文件；本进程仍独占麦克风，所以要按 bridge 的 tts_active 做回声屏蔽。"""
    def __init__(self,timeout=None,poll=None,speak=None):
        # Normal chat uses the same student's brain/public HTTPS endpoint as English.
        # The legacy local bridge remains opt-in for backwards compatibility.
        self.url=os.environ.get('CHAT_URL') or os.environ.get('BRAIN_URL','').rstrip('/')
        token=os.environ.get('CHAT_TOKEN') or os.environ.get('EDGE_TOKEN','')
        self.headers={'Authorization':'Bearer '+token} if token else {}
        self.timeout=float(os.environ.get('CHAT_TIMEOUT','120')) if timeout is None else timeout
        self.poll=poll or self.request
        self.remote= poll is None and bool(self.url and token)
        self.speak_audio=speak
        self.session_id=uuid.uuid4().hex
        self.until=0.;self.guard_until=0.;self.last_poll=0.;self.history=[];self.muted=False

    def local_ack(self):
        """唤醒应答是固定话术“我在，你想聊什么？”，预置在本机直接播。
        走云端要两次请求加一次合成（实测 3 秒），本地播只要 0.1 秒。"""
        return read_reply_audio(os.environ.get('CHAT_ACK_AUDIO','/opt/english-class/data/replies/chat_ack.wav'))

    def _speak_result(self,result):
        if self.muted: return
        if not self.remote or not self.speak_audio: return
        segments=result.get('segments',[]) if isinstance(result,dict) else []
        if not segments: return
        with httpx.Client(timeout=httpx.Timeout(90,connect=10),trust_env=False) as c:
            r=c.post(self.url+'/voice/speech',headers=self.headers,
                     json={'segments':segments,'slow':False})
            if r.status_code>=400: raise RuntimeError(f'普通聊天语音返回{r.status_code}')
        self.speak_audio(r.content)

    def request(self,method,path,body=None):
        if self.remote and path in ('/command','/voice/input'):
            action='enter' if path=='/command' else 'answer'
            text='' if body is None else str(body.get('text',''))
            payload={'action':action,'text':text,'request_id':uuid.uuid4().hex,'session_id':self.session_id}
            with httpx.Client(timeout=httpx.Timeout(90,connect=10),trust_env=False) as c:
                r=c.post(self.url+'/chat/turn',headers=self.headers,json=payload)
            if r.status_code>=400: raise RuntimeError(f'普通聊天服务返回{r.status_code}')
            result=r.json(); self._speak_result(result); return result
        with httpx.Client(timeout=httpx.Timeout(10,connect=3),trust_env=False) as c:
            r=c.request(method,self.url+path,headers=self.headers,json=body)
            if r.status_code>=400: raise RuntimeError(f'原机器人bridge返回{r.status_code}')
            return r.json()

    @property
    def active(self): return time.monotonic()<self.until

    def enter(self):
        """听到单独的“小陈同学”：进入/延长聊天。先在本机应一声“我在”，云端只负责建会话。"""
        self.until=time.monotonic()+self.timeout;self.guard_until=time.monotonic()+1.5
        ack=self.local_ack()
        if ack and self.speak_audio:
            try: self.speak_audio(ack)
            except Exception as exc: LOG.warning('本地应答播放失败：%s',exc);ack=None
            else: self.guard_until=time.monotonic()+1.5
        self.muted=bool(ack)  # 本机已经说过同一句，云端返回的这段不再重复播
        try: self.poll('POST','/command',{'cmd':'speak_ack'})
        except Exception as exc: LOG.warning('普通聊天没有应答：%s',exc);return False
        finally: self.muted=False
        LOG.info('进入普通聊天 应答=%s',('本机' if ack else '云端'))
        return True

    def say(self,text,had_wake):
        self.until=time.monotonic()+self.timeout
        body={'text':text,'had_wake_word':had_wake,'in_conversation':True,'recent_context':self.history[-3:]}
        try:
            result=self.poll('POST','/voice/input',body)
            ok=(result.get('ok') is True) or (self.remote and result.get('phase')=='chat')
        except Exception as exc: LOG.warning('普通聊天转交失败：%s',exc);ok=False
        if ok:
            self.history=(self.history+[text])[-5:];self.guard_until=time.monotonic()+2.0
            LOG.info('普通聊天转交 chars=%d',len(text))
        return ok

    def leave(self):
        if self.active: LOG.info('退出普通聊天')
        self.until=0.;self.history=[]

    def guarded(self,now):
        """原机器人正在说话（或刚发出去等它开口）时不收麦克风声音。每 0.25 秒问一次 bridge。"""
        if now-self.last_poll>=0.25:
            self.last_poll=now
            try:
                if self.poll('GET','/voice/tts_active').get('tts_active'): self.guard_until=max(self.guard_until,now+0.8)
            except Exception: pass
        return now<self.guard_until


def load_env(path:Path):
    for line in path.read_text(encoding='utf-8').splitlines():
        line=line.strip()
        if not line or line.startswith('#'): continue
        k,v=line.split('=',1);v=v.strip()
        if v[:1] in ('"',"'"): v=shlex.split(v)[0]
        os.environ[k.strip()]=v

class Edge:
    def __init__(self,play_audio=True,start_worker=True,display_text=False):
        self.url=os.environ.get('BRAIN_URL','').rstrip('/');self.token=os.environ.get('EDGE_TOKEN','')
        if not self.url or len(self.token)<16: raise ValueError('请填写BRAIN_URL和本人的EDGE_TOKEN')
        p=urlsplit(self.url)
        if p.scheme not in ('http','https') or not p.hostname: raise ValueError('脑端地址必须是HTTP(S) URL')
        if p.scheme=='http' and os.environ.get('ALLOW_INSECURE_HTTP','0')!='1':
            raise ValueError('默认只允许HTTPS；仅可信局域网/Tailscale测试可由老师设置ALLOW_INSECURE_HTTP=1')
        self.headers={'Authorization':'Bearer '+self.token}
        self.audio_enabled=play_audio;self.display_text=display_text
        self.active=False;self.busy=False;self.playing=False
        self.phase='idle';self.player=None;self.generation=0;self.last_activity=time.monotonic()
        # spoken：机器人每出一道新题（回答/控制后的回复）加1；录音时记下，处理时若已换题则作废。
        self.spoken=0;self.question_key=None
        self.queue=queue.Queue(maxsize=4);self.stop_event=threading.Event();self.last_result=None
        # The last completed lesson's feedback is replayable without another
        # Tutor turn. Keep only this spoken reply in memory, never in the journal;
        # idle status updates must not overwrite it. Start/stop explicitly clear it.
        self.final_reply=None
        self.pending=None;self.retry_at=0.;self.retry_count=0;self.stop_queued=False
        state=os.environ.get('EDGE_PENDING_PATH') or (str(Path(os.environ['STATE_DIRECTORY'])/'pending-turn.json')
                                                     if os.environ.get('STATE_DIRECTORY') else None)
        self.pending_path=Path(state) if state else None
        # A state file belongs to this exact brain/credential, never to another
        # classroom selected later in pi.env. The credential itself is not saved.
        self.endpoint_id=hashlib.sha256((self.url+'\0'+self.token).encode()).hexdigest()
        self.load_pending()
        self.thread=threading.Thread(target=self.worker,name='english-network',daemon=True)
        if start_worker: self.thread.start()

    def request(self,path,*,body=None,content=None,params=None,raw=False):
        headers=dict(self.headers)
        if content is not None: headers['Content-Type']='audio/wav'
        with httpx.Client(timeout=httpx.Timeout(110,connect=10)) as c:
            r=c.post(self.url+path,headers=headers,json=body,content=content,params=params)
            if r.status_code>=400:
                try: detail=r.json().get('detail','请求失败')
                except ValueError: detail='请求失败'
                raise BrainRequestError(r.status_code,detail)
            return r.content if raw else r.json()

    def load_pending(self):
        if not self.pending_path or not self.pending_path.exists(): return
        try:
            data=json.loads(self.pending_path.read_text(encoding='utf-8'))
            if data.get('version')!=1: raise ValueError('unsupported recovery format')
            if data.get('endpoint_id')!=self.endpoint_id or not 0<=time.time()-data['item']['created_at']<=RECOVERY_TTL_SECONDS:
                self.pending_path.unlink();return
            item=data['item']
            if item.get('wav') is not None: item['wav']=base64.b64decode(item['wav'],validate=True)
            self.pending=item
            self.last_result=data.get('last_result')
            if self.last_result:
                self.active=self.last_result['active'];self.phase=self.last_result['phase']
                self.note_question(self.last_result)
            self.generation=item['generation'];self.spoken=item.get('spoken',self.spoken)
            LOG.info('发现未确认回合；先确认原请求，再接收新题答案')
        except (OSError,ValueError,KeyError,TypeError) as exc:
            raise ValueError('未确认回合文件不可用；请检查状态目录，避免重复提交') from exc

    def save_pending(self):
        if not self.pending_path or not self.pending: return
        item=copy.deepcopy(self.pending)
        if item.get('wav') is not None: item['wav']=base64.b64encode(item['wav']).decode('ascii')
        private_json_write(self.pending_path,{'version':1,'endpoint_id':self.endpoint_id,
                                             'item':item,'last_result':self.last_result})

    def clear_pending(self):
        if self.pending_path: self.pending_path.unlink(missing_ok=True)
        self.pending=None;self.retry_count=0;self.retry_at=0.

    @property
    def starting(self):
        """A queued/unconfirmed start is cancellable before active becomes true."""
        pending=self.pending
        if pending and pending.get('action')=='start': return True
        with self.queue.mutex:
            return any(item.get('action')=='start' for item in self.queue.queue)

    def submit(self,action='answer',text='',wav=None,question=None):
        dismiss_final=(action=='stop' and not self.active and self.final_reply is not None
                       and not self.pending and not self.starting)
        if action=='repeat' and not self.active and self.final_reply is not None and not self.starting:
            action='replay_final'
        if action in ('start','stop','pause'):
            self.stop_queued=False
            self.generation+=1;self.stop_audio()
            while True:
                try: self.queue.get_nowait();self.queue.task_done()
                except queue.Empty: break
        if action in ('start','stop'): self.final_reply=None
        if dismiss_final: return True  # Brain already confirmed done; cancel locally.
        # Capture the server's question identity at recording time, not when a
        # network worker eventually sends this item after another turn completes.
        identity=question if question is not None else (self.last_result or {})
        item={'generation':self.generation,'action':action,'text':text,'wav':wav,'request_id':uuid.uuid4().hex,'spoken':self.spoken}
        if action=='replay_final': item['reply']=copy.deepcopy(self.final_reply)
        for key in ('session_id','question_id'):
            if key in identity: item[key]=identity[key]
        if action=='stop': self.stop_queued=True
        try: self.queue.put_nowait(item);return True
        except queue.Full:
            LOG.warning('待处理的语音太多，这一句没有发送');return False

    def submit_tick(self):
        """只在完全空闲时轮询：不忙、不在播放、队列里没有待处理的回答。"""
        if self.pending or self.busy or self.playing or not self.queue.empty(): return False
        return self.submit('tick')

    def stop_audio(self):
        player=self.player
        if player and player.poll() is None:
            try: player.terminate()
            except OSError: pass
        self.playing=False

    def local_message(self,text,audio=None):
        LOG.info(text)
        if not self.audio_enabled: return
        if audio is None:
            name=MESSAGE_AUDIO.get(text)
            if name: audio=os.path.join(REPLY_AUDIO_DIR,name)
        self.playing=True
        try:
            wav=read_reply_audio(audio)
            if wav:
                LOG.info('预置音频 bytes=%d',len(wav))
                self.play(wav)
                return
            if audio: LOG.warning('预置音频不可用，回退本机合成：%s',audio)
            # Use the same ALSA route as lesson audio. Direct hw USB output
            # rejected mono speech in deployment; plughw performs conversion.
            result=subprocess.run(['espeak-ng','--stdout','-v',os.environ.get('LOCAL_VOICE','cmn'),'-s','155',text],
                                  stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=12,check=True)
            self.play(result.stdout)
        except (OSError,subprocess.SubprocessError,RuntimeError) as exc:
            LOG.error('本地提示音播放失败：%s',type(exc).__name__)
        finally: self.playing=False;self.player=None

    def play(self,wav):
        if not self.audio_enabled: return
        self.playing=True
        try:
            self.player=subprocess.Popen(['aplay','-q','-D',os.environ.get('PLAYBACK_DEVICE','default')],stdin=subprocess.PIPE)
            self.player.communicate(wav,timeout=120)
            if self.player.returncode and self.player.returncode>0:
                raise RuntimeError('音频播放失败，请检查PLAYBACK_DEVICE和USB耳麦')
        except (OSError,subprocess.SubprocessError):
            self.stop_audio()
            raise RuntimeError('音频播放失败，请检查PLAYBACK_DEVICE和USB耳麦')
        finally: self.playing=False;self.player=None;self.last_activity=time.monotonic()

    def worker(self):
        while not self.stop_event.is_set():
            if self.pending and not self.stop_queued:
                if time.monotonic()>=self.retry_at:
                    try: self.retry_pending()
                    except OSError:
                        LOG.error('无法更新未确认回合文件；等待状态目录恢复')
                        self.retry_at=time.monotonic()+30
                else: self.stop_event.wait(min(.3,max(0.,self.retry_at-time.monotonic())))
                continue
            try: item=self.queue.get(timeout=0.3)
            except queue.Empty: continue
            try: self.process(item)
            finally: self.queue.task_done()

    def retry_pending(self):
        if not self.pending: return
        if time.time()-self.pending['created_at']>RECOVERY_TTL_SECONDS:
            # Explicitly stop the unconfirmed session when its recovery window
            # expires. A lost stop reply itself remains idempotently recoverable.
            self.pending={'generation':self.generation,'action':'stop','text':'','wav':None,
                          'request_id':uuid.uuid4().hex,'spoken':self.spoken,'created_at':time.time()}
            self.save_pending()
        self.process(self.pending)

    def process(self,item):
        if item['action']=='replay_final':
            self.replay_final(item)
            return
        recovering=self.pending is not None and self.pending['request_id']==item['request_id']
        if self.pending and not recovering and item['action']!='stop':
            LOG.info('上一回合未确认；冻结后续答案，保留原请求编号');return
        if not recovering and item['action']=='answer' and (item.get('spoken',self.spoken)!=self.spoken or
                (item.get('question_id') and self.last_result and item['question_id']!=self.last_result.get('question_id'))):
            # 这句是在上一题时录的，机器人已经换了新题；不拿它判新题。
            LOG.info('丢弃换题前录下的一句回答');return
        self.busy=True;received=False
        try:
            if item['action']=='stop': self.stop_queued=False
            self.pending=copy.deepcopy(item)
            self.pending.setdefault('created_at',time.time())
            self.save_pending()  # Do not send a write-capable turn before its ID is recoverable.
            if item['wav'] is not None:
                params={k:item[k] for k in ('request_id','session_id','question_id') if k in item}
                result=self.request('/voice/audio',content=item['wav'],params=params)
            else:
                body={k:item[k] for k in ('action','text','request_id','session_id','question_id') if k in item}
                if item['action'] in ('start','stop','pause','resume'):
                    # These are explicit session controls. In particular stop
                    # must remain usable after a committed reply was lost and
                    # the Pi still holds the previous question identity.
                    body.pop('session_id',None);body.pop('question_id',None)
                result=self.request('/voice/turn',body=body)
            received=True
            self.active=result['active'];self.phase=result['phase'];self.last_result=result
            segments=result.get('segments',[])
            self.note_question(result)
            self.clear_pending()
            if item['generation']!=self.generation: return
            if not self.active and self.phase=='done' and segments:
                self.final_reply={'phase':'done','segments':copy.deepcopy(segments),'slow':result.get('slow',False)}
            if self.speak_reply(result,item['generation']) and self.active: self.report_played()
        except Exception as exc:
            LOG.error('%s',exc)
            failure_message='连接暂时有问题。正在确认上一轮，请先等待；也可以说结束练习。'
            if not received:
                if isinstance(exc,BrainRequestError) and exc.status==409 and isinstance(exc.detail,dict) and exc.detail.get('code')=='stale_question':
                    current=exc.detail['current']
                    self.active=current['active'];self.phase=current['phase'];self.last_result=current
                    self.note_question(current);self.clear_pending()
                    failure_message='这段录音属于上一题。请说，再说一次，听当前题目后再回答。'
                elif isinstance(exc,BrainRequestError) and exc.status in (400,413,422):
                    self.clear_pending()  # Rejected before a valid turn; retrying identical bytes cannot help.
                    failure_message='这次请求未被接受。请重新回答当前题目。'
                else:
                    self.retry_count+=1
                    self.retry_at=time.monotonic()+min(30,2**min(self.retry_count,5))
            if item['generation']==self.generation:
                self.local_message('播报暂时没有完成。请说，再说一次，听当前题目。' if received else
                                   failure_message)
        finally:
            self.busy=False;self.last_activity=time.monotonic()

    def speak_reply(self,result,generation):
        segments=result.get('segments',[])
        if not segments or generation!=self.generation: return False
        LOG.info('播报 phase=%s segments=%d chars=%d',result.get('phase'),len(segments),
                 sum(len(s['text']) for s in segments))
        if self.display_text: print('机器人：'+' '.join(s['text'] for s in segments),flush=True)
        if self.audio_enabled:
            # 流式接收：边接收边播放，降低感知延迟
            headers=dict(self.headers)
            with httpx.Client(timeout=httpx.Timeout(110,connect=10)) as c:
                with c.stream('POST', self.url+'/voice/speech', 
                             headers=headers, 
                             json={'segments':segments,'slow':result.get('slow',False)}) as stream:
                    if stream.status_code>=400:
                        stream.read()  # 消耗完响应
                        try: detail=stream.json().get('detail','请求失败')
                        except ValueError: detail='请求失败'
                        raise BrainRequestError(stream.status_code,detail)
                    
                    # 流式播放：一次性收完再播（避免分段播放导致 WAV 头解析错误）
                    # TODO: 真正的流式需要在第一段保留 WAV 头，后续段拼接纯 PCM
                    data = stream.read()
                    if generation==self.generation:
                        self.play(data)
        return generation==self.generation

    def replay_final(self,item):
        # Never create a new write-capable turn or a pending audio upload for a
        # playback retry. Stop/new start invalidate both queued and in-flight TTS.
        if self.active or self.final_reply is None or item['generation']!=self.generation: return
        self.busy=True
        try:
            self.speak_reply(item['reply'],item['generation'])
        except Exception as exc:
            LOG.error('%s',exc)
            if item['generation']==self.generation:
                self.local_message('播报暂时没有完成。请说，再说一次，听结束点评。')
        finally:
            self.busy=False;self.last_activity=time.monotonic()

    def note_question(self,result):
        """题目位置变了（开始/换词/换阶段/对话下一轮）才算换题；“没听清再说一次”不算。
        对话阶段的轮次用脑端返回的 dialog_count 区分，不能用“有没有播报内容”判断——没听清的重问也有播报。"""
        key=(result.get('session_id'),result.get('question_id')) if result.get('question_id') else (
             result.get('session_id'),result.get('phase'),result.get('word_index'),result.get('dialog_count'))
        if key!=self.question_key: self.spoken+=1
        self.question_key=key

    def report_played(self):
        """告诉脑端“刚播完”，20秒重问从播完开始算；失败只记日志，不打断上课。"""
        identity={k:self.last_result[k] for k in ('session_id','question_id') if self.last_result and k in self.last_result}
        try: self.request('/voice/turn',body={'action':'played','text':'','request_id':uuid.uuid4().hex,**identity})
        except Exception as exc: LOG.warning('播完通知失败：%s',exc)

    def close(self):
        self.stop_event.set();self.stop_audio();self.final_reply=None


def recognize_chinese(model,wav):
    """本机中文识别，返回 (文字, 平均置信度)。"""
    import vosk
    with wave.open(io.BytesIO(wav),'rb') as w: pcm=w.readframes(w.getnframes())
    rec=vosk.KaldiRecognizer(model,16000);rec.SetWords(True)
    rec.AcceptWaveform(pcm);result=json.loads(rec.FinalResult())
    words=result.get('result',[])
    confidence=sum(w.get('conf',0) for w in words)/len(words) if words else 0
    return result.get('text',''),confidence


def recognize_control(model,wav):
    text,confidence=recognize_chinese(model,wav)
    # Control recognition is not constrained to one expected answer.
    return control_action(text) if confidence>=0.70 else None


def heard_wake(partial:str) -> bool:
    return any(w in partial.replace(' ','') for w in WAKE_WORDS)


def route(edge,chat,text,confidence,wav,question=None):
    """一段语音的去向。上课优先：课中“小陈同学”只打断播报，不切去聊天。
    空闲时“小陈同学，学英语”上课，“小陈同学”聊天；聊天中的后续句子转交原机器人，再说“小陈同学，学英语”可直接切到上课。"""
    # 进入类指令（上课/聊天）阈值放宽到 0.60：唤醒词必须说对，但 Vosk 对
    # 真人说话的平均置信度经常在 0.6-0.7 之间，0.70 会把正确的唤醒也丢掉。
    # 课中控制指令（停止/暂停等）保持 0.70，避免误触发。
    action=control_action(text)
    had_wake,rest=split_wake(text)
    if action=='start':
        # 听到唤醒词后句子变长，Vosk 平均置信度常被拉到 0.5-0.6；此时意图已经很明确
        # （必须带“英语/上课”），门槛跟着放宽，否则正确的“小陈同学，学英语”会被丢掉。
        if confidence<(0.45 if had_wake else 0.60): action=None
    elif action=='chat':
        # 只喊唤醒词时保持原门槛：太低会把环境杂音当成“叫我了”，一直挂在聊天状态。
        if confidence<0.60: action=None
    elif confidence<0.70:
        action=None
    if action=='start':
        chat.leave()
        if not edge.active and not edge.starting:
            edge.submit('start');LOG.info('进入英语课堂')
        return 'start'
    if action=='stop' and edge.starting:
        chat.leave()
        edge.submit('stop')
        return 'stop'
    if edge.active:
        if action=='chat': edge.generation+=1;edge.stop_audio();return 'interrupt'
        if action: edge.submit(action);return action
        if edge.phase!='paused': edge.submit(wav=wav,question=question);return 'answer'
        return None
    if edge.final_reply is not None and action in ('repeat','stop') and not edge.starting:
        edge.submit(action)
        return action
    if action=='chat':
        if chat.enter() is False:
            chat.leave()
            edge.local_message('我在。普通聊天服务尚未连接，请说，小陈同学，学英语，进入英语课堂。')
        return 'chat'
    if chat.active and (had_wake or confidence>=0.5) and len(rest)>=2:
        chat.say(rest,had_wake);return 'say'
    # Idle environmental speech is never sent anywhere.
    return None


def voice_loop(edge,chat=None):
    chat=chat or Chat(speak=edge.play)
    import vosk
    model_path=Path(os.environ.get('VOSK_ZH_PATH','models/vosk-model-small-cn-0.22'))
    if not model_path.is_dir(): raise RuntimeError('中文唤醒模型不存在：先安装模型或指向原aibot中文模型目录')
    vosk.SetLogLevel(-1);model=vosk.Model(str(model_path))
    wake=vosk.KaldiRecognizer(model,16000)
    capture=os.environ.get('CAPTURE_DEVICE','auto')
    if capture=='auto': capture=find_usb_mic()
    gain=float(os.environ.get('MIC_GAIN','1'));threshold=float(os.environ.get('VAD_THRESHOLD','450'))
    if not 0.25<=gain<=8 or not 50<=threshold<=10000: raise ValueError('MIC_GAIN应在0.25—8，VAD_THRESHOLD应在50—10000')
    vad=VoiceActivity(threshold=threshold,log=LOG.info)
    proc=subprocess.Popen(['arecord','-q','-D',capture,'-t','raw','-f','S16_LE','-r','16000','-c','1'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    edge.local_message(READY_MESSAGE,audio=READY_AUDIO)
    guard_until=time.monotonic()+0.4;was_playing=False;last_tick=time.monotonic();recording_question=None
    try:
        while not edge.stop_event.is_set():
            chunk=proc.stdout.read(3200)
            if not chunk: raise RuntimeError('麦克风采集停止，systemd将重启服务')
            chunk=amplify(chunk,gain)
            now=time.monotonic()
            if edge.playing:
                was_playing=True;vad.reset()
                if wake.AcceptWaveform(chunk):
                    heard=json.loads(wake.Result()).get('text','');action=control_action(heard)
                    if action in ('stop','pause'): edge.submit(action)
                else:
                    partial=json.loads(wake.PartialResult()).get('partial','')
                    if heard_wake(partial):
                        edge.generation+=1;edge.stop_audio();guard_until=now+0.4
                        wake=vosk.KaldiRecognizer(model,16000)
                continue
            if was_playing:
                was_playing=False;guard_until=now+0.35;vad.reset();wake=vosk.KaldiRecognizer(model,16000)
            # Chinese stop/pause remains usable while waiting for a network response.
            if now<guard_until or (not edge.active and chat.active and chat.guarded(now)):
                vad.reset();continue
            was_recording=bool(vad.parts)
            captured_question=copy.deepcopy(edge.last_result or {})
            wav=vad.feed(chunk)
            if not was_recording and (vad.parts or wav): recording_question=captured_question
            if wav:
                text,confidence=recognize_chinese(model,wav)
                # 10 字以内的短句基本都是唤醒/控制指令，记下正文便于排查识别偏差；
                # 长句是对话正文，只记长度（项目约定不落对话内容）。
                LOG.info('识别 chars=%d conf=%.2f%s',len(text),confidence,
                         (' text='+text) if 0<len(text)<=10 else '')
                route(edge,chat,text,confidence,wav,question=recording_question)
                recording_question=None
            # 5 秒轮询一次，脑端据此判断 20 秒重问、3 分钟自动暂停（服务器决定，这里不计时）。
            if now-last_tick>TICK_SECONDS and edge.submit_tick(): last_tick=now
    finally:
        proc.terminate()
        try: proc.wait(timeout=3)
        except subprocess.TimeoutExpired: proc.kill()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--env',type=Path,default=Path('/etc/english-class/pi.env'))
    p.add_argument('--text',action='store_true',help='键盘输入调试，无需Vosk或麦克风')
    p.add_argument('--no-audio',action='store_true',help='文字调试不播声音')
    a=p.parse_args();logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)  # 5 秒一次轮询，避免日志刷屏；默认不记录对话正文
    if a.env.is_file(): load_env(a.env)
    edge=Edge(play_audio=not a.no_audio,display_text=a.text)
    signal.signal(signal.SIGTERM,lambda *_:edge.close())
    try:
        if a.text:
            print('输入 /start 开始，/stop 结束，/quit 退出；其他文字为回答。')
            while not edge.stop_event.is_set():
                try: text=input('你：').strip()
                except EOFError: break
                if text=='/quit': break
                action={'/start':'start','/stop':'stop','/pause':'pause','/resume':'resume','/repeat':'repeat','/help':'help'}.get(text,'answer')
                edge.submit(action,text if action=='answer' else '');edge.queue.join()
        else: voice_loop(edge)
    except KeyboardInterrupt: pass
    finally: edge.close()

if __name__=='__main__': main()
