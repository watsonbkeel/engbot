import importlib.util
import json
from pathlib import Path
import pytest


def test_provision_creates_only_student_credentials(db,tmp_path):
    from english_class.provision import provision
    out=tmp_path/'s001'
    provision(db,'s001',9101,out,'http://127.0.0.1:18090','https://class.example/api-host','https://class.example/students/s001')
    brain=(out/'brain.env').read_text();pi=(out/'pi.env').read_text();mini=(out/'english-env.local.js').read_text()
    assert 'LLM_API_KEY' not in brain+pi+mini
    assert 'BRAIN_TOKEN=' in brain and 'EDGE_TOKEN=' in pi
    assert 'BRAIN_TOKEN' not in pi+mini
    assert '9101' in brain
    assert db.config('s001')['unit']==0
    with pytest.raises(ValueError): provision(db,'s001',9101,out,'http://x','https://x','https://y')


def test_source_hash_detects_modified_dictionary():
    from english_class.sources import git_blob_sha, verify_blob
    raw=b'hello\n'
    assert git_blob_sha(raw)=='ce013625030ba8dba906f756967f9e9ca394464a'
    with pytest.raises(ValueError): verify_blob(raw,'0000000000000000000000000000000000000000')


def test_miniprogram_merge_preserves_original(tmp_path):
    from english_class.sources import merge_miniprogram
    src=tmp_path/'original';src.mkdir()
    (src/'app.json').write_text(json.dumps({'pages':['pages/learn/index'],'tabBar':{'list':[{'pagePath':'pages/learn/index','text':'学习'}]}}))
    (src/'app.js').write_text('App({original: true})')
    dest=tmp_path/'merged'
    overlay=Path(__file__).resolve().parents[1]/'miniprogram'
    merge_miniprogram(src,overlay,dest)
    cfg=json.loads((dest/'app.json').read_text())
    assert cfg['pages'][0]=='pages/today/index'
    assert set(json.loads((overlay/'app.json').read_text())['pages']).issubset(cfg['pages'])
    assert (dest/'utils/page-state.js').exists()
    assert (dest/'utils/pi-status.js').exists()
    assert (dest/'pages/today/index.wxss').read_text().startswith('@import')
    assert 'tabPages' in (dest/'utils/english-origin.js').read_text()
    assert 'pages/learn/index' in cfg['pages']
    assert cfg['tabBar']['list'][0]['text']=='学习'
    assert (dest/'app.js').read_text()=='App({original: true})'
    assert json.loads((src/'app.json').read_text())['pages']==['pages/learn/index']
    with pytest.raises(ValueError): merge_miniprogram(src,overlay,dest)


def test_no_extract_path_traversal(tmp_path):
    import io, zipfile
    from english_class.sources import extract_archive
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z: z.writestr('../bad.txt','bad')
    with pytest.raises(ValueError): extract_archive(buf.getvalue(),tmp_path/'out')


def test_pi_command_and_vad_no_training_on_silence():
    from pi.audio import VoiceActivity, control_action
    import array
    v=VoiceActivity(threshold=100,silence_chunks=2,max_chunks=20)
    assert all(v.feed(b'\x00'*3200) is None for _ in range(5))
    speech=array.array('h',[1000]*1600).tobytes()
    assert v.feed(speech) is None
    assert v.feed(b'\x00'*3200) is None
    wav=v.feed(b'\x00'*3200)
    assert wav and wav.startswith(b'RIFF')
    assert control_action('我 不 会')=='howtosay'
    assert control_action('do not stop') is None


def test_two_wake_states():
    """“小陈同学，学英语”=上课；只说“小陈同学”=普通聊天；旧唤醒词小爱同学不再生效。"""
    from pi.audio import control_action, split_wake
    from english_class.engine import command
    assert control_action('小陈 同学')=='chat'
    assert control_action('小陈同学。')=='chat'
    assert control_action('小晨 同学')=='chat'                      # Vosk 同音误识别
    assert control_action('小陈 同学 学 英语')=='start'
    assert control_action('小陈同学，开始英语练习')=='start'
    assert control_action('学 英语')=='start'
    assert control_action('小陈 同学 暂停')=='pause'
    assert control_action('小陈 同学 今天 天气 怎么样') is None    # 聊天内容交给 route，不是课堂指令
    assert control_action('小爱同学') is None
    assert split_wake('小陈 同学 今天 天气 怎么样')==(True,'今天天气怎么样')
    assert split_wake('今天天气')==(False,'今天天气')
    assert command('小陈同学学英语')=='start' and command('小陈同学，开始今天的英语练习')=='start'


def _idle_edge(monkeypatch):
    from pi.english_voice import Edge
    monkeypatch.setenv('BRAIN_URL','https://brain.example');monkeypatch.setenv('EDGE_TOKEN','edge-token-1234567890')
    edge=Edge(play_audio=False,start_worker=False)
    edge.stop_audio=lambda:None
    return edge


def test_local_notice_uses_configured_audio_route(monkeypatch):
    import subprocess
    from pi import english_voice
    edge=_idle_edge(monkeypatch)
    edge.audio_enabled=True
    played=[]
    monkeypatch.setattr(edge,'play',played.append)
    def synth(args,**kwargs):
        assert '--stdout' in args
        assert kwargs['check'] is True
        return subprocess.CompletedProcess(args,0,stdout=b'RIFF-test',stderr=b'')
    monkeypatch.setattr(english_voice.subprocess,'run',synth)
    edge.local_message('测试')
    assert played==[b'RIFF-test']
    assert edge.playing is False


def test_missing_chat_bridge_gives_local_notice(monkeypatch):
    from pi.english_voice import Chat,route
    edge=_idle_edge(monkeypatch)
    notices=[]
    edge.local_message=notices.append
    def unavailable(*args):
        raise ConnectionRefusedError('bridge unavailable')
    chat=Chat(poll=unavailable)
    assert route(edge,chat,'小陈同学',.99,b'')=='chat'
    assert not chat.active
    assert len(notices)==1 and '普通聊天服务尚未连接' in notices[0]


def _chat(calls):
    from pi.english_voice import Chat
    def poll(method,path,body=None):
        calls.append((path,body));return {'ok':True,'tts_active':False}
    return Chat(timeout=60,poll=poll)


def _actions(edge):
    out=[]
    while not edge.queue.empty(): out.append(edge.queue.get_nowait()['action']);edge.queue.task_done()
    return out


def test_route_idle_wake_only_goes_to_original_bot(monkeypatch):
    from pi.english_voice import route
    edge=_idle_edge(monkeypatch);calls=[];chat=_chat(calls)
    assert route(edge,chat,'小陈 同学',0.9,b'RIFF')=='chat'
    assert chat.active and calls==[('/command',{'cmd':'speak_ack'})] and _actions(edge)==[]
    assert route(edge,chat,'今天 天气 怎么样',0.9,b'RIFF')=='say'
    assert calls[-1][0]=='/voice/input' and calls[-1][1]['text']=='今天天气怎么样' and calls[-1][1]['had_wake_word'] is False
    assert route(edge,chat,'小陈 同学 讲 个 笑话',0.9,b'RIFF')=='say'
    assert calls[-1][1]['text']=='讲个笑话' and calls[-1][1]['had_wake_word'] is True
    assert calls[-1][1]['recent_context']==['今天天气怎么样']
    assert _actions(edge)==[]                                        # 聊天内容从不发到英语脑端
    assert route(edge,chat,'嗯',0.9,b'RIFF') is None                  # 太短的碎片不转交
    assert route(edge,chat,'小陈 同学 学 英语',0.9,b'RIFF')=='start'
    assert not chat.active and _actions(edge)==['start']              # 聊天中可直接切到上课


def test_route_idle_speech_without_wake_goes_nowhere(monkeypatch):
    from pi.english_voice import route
    edge=_idle_edge(monkeypatch);calls=[];chat=_chat(calls)
    assert route(edge,chat,'今天 天气 怎么样',0.9,b'RIFF') is None
    assert route(edge,chat,'小陈 同学',0.5,b'RIFF') is None            # 置信度不够不唤醒
    assert calls==[] and _actions(edge)==[]


def test_route_in_class_wake_only_interrupts(monkeypatch):
    from pi.english_voice import route
    edge=_idle_edge(monkeypatch);calls=[];chat=_chat(calls)
    edge.active=True;edge.phase='speak';g=edge.generation
    assert route(edge,chat,'小陈 同学',0.9,b'RIFF')=='interrupt'
    assert edge.generation==g+1 and not chat.active and calls==[]
    assert route(edge,chat,'小陈 同学 学 英语',0.9,b'RIFF')=='start' and _actions(edge)==[]   # 课中不重复开始
    assert route(edge,chat,'apple',0.3,b'RIFF')=='answer' and _actions(edge)==['answer']
    assert route(edge,chat,'小陈 同学 暂停',0.9,b'RIFF')=='pause'
    edge.phase='paused';assert route(edge,chat,'apple',0.3,b'RIFF') is None


def test_chat_guard_follows_original_bot_tts(monkeypatch):
    from pi.english_voice import Chat
    import time
    state={'tts':True}
    chat=Chat(timeout=60,poll=lambda m,p,b=None:{'ok':True,'tts_active':state['tts']})
    now=time.monotonic()
    assert chat.guarded(now)                                          # 原机器人在说话：不收音
    state['tts']=False
    assert not chat.guarded(now+2)                                    # 停了 0.8 秒后恢复收音


def test_wave_validation():
    from english_class.providers import pcm_wav,validate_wav
    wav=pcm_wav(b'\x00'*3200)
    assert validate_wav(wav)==(b'\x00'*3200,16000)
    with pytest.raises(ValueError): validate_wav(b'not wave')

def test_provision_does_not_create_student_if_files_cannot_be_written(db,tmp_path):
    from english_class.provision import provision
    blocked=tmp_path/'not-a-directory';blocked.write_text('occupied')
    with pytest.raises(OSError):
        provision(db,'s003',9103,blocked/'s003','http://127.0.0.1:18090','https://class.example','https://class.example/students/s003')
    with pytest.raises(ValueError): db.config('s003')


def test_public_port_default_avoids_known_conflict_and_is_single_sourced(monkeypatch):
    # 目标服务器 127.0.0.1:18080 已被其他生产服务(flower)占用；默认端口不得再用 18080，
    # 且代码、配置模板、安装脚本必须用同一来源，不能各自写死。
    from english_class import DEFAULT_PUBLIC_PORT
    assert DEFAULT_PUBLIC_PORT==18090
    root=Path(__file__).resolve().parents[1]
    env=(root/'deploy/public.env.example').read_text()
    assert f'PUBLIC_PORT={DEFAULT_PUBLIC_PORT}' in env
    nginx=(root/'deploy/nginx-locations.conf.example').read_text()
    assert f'127.0.0.1:{DEFAULT_PUBLIC_PORT};' in nginx
    for rel in ('english_class/run.py','english_class/brain_api.py','english_class/cli.py',
                'scripts/install_server.sh','scripts/create_student.sh'):
        assert '18080' not in (root/rel).read_text(),rel
    monkeypatch.delenv('PUBLIC_URL',raising=False)
    import english_class.brain_api as b
    seen={}
    monkeypatch.setattr(b,'PublicClient',lambda url,*a:seen.setdefault('url',url))
    monkeypatch.setattr(b,'create_brain',lambda *a,**k:None)
    for k,v in {'STUDENT_ID':'s001','BRAIN_TOKEN':'x'*20,'EDGE_TOKEN':'y'*20}.items(): monkeypatch.setenv(k,v)
    b.from_env()
    assert seen['url']==f'http://127.0.0.1:{DEFAULT_PUBLIC_PORT}'


def test_install_health_check_verifies_it_is_our_service():
    # 端口上若是别的服务，安装器不能把它的200当成本服务健康。
    script=(Path(__file__).resolve().parents[1]/'scripts/install_server.sh').read_text()
    assert "['service']=='public'" in script


def test_pi_tick_is_frequent_enough_for_20s_reask_and_brain_has_state_dir():
    from pi.english_voice import TICK_SECONDS
    from english_class.engine import REASK_SECONDS
    assert TICK_SECONDS<=REASK_SECONDS/4
    unit=(Path(__file__).resolve().parents[1]/'deploy/english-brain@.service').read_text()
    assert 'StateDirectory=english-class-brain/%i' in unit


def test_pi_playback_failure_is_not_silent(monkeypatch):
    from pi.english_voice import Edge
    class FailedPlayer:
        returncode=1
        def communicate(self,*args,**kwargs): pass
        def poll(self): return 1
    monkeypatch.setattr('pi.english_voice.subprocess.Popen',lambda *a,**k:FailedPlayer())
    edge=object.__new__(Edge);edge.audio_enabled=True;edge.playing=False;edge.player=None
    with pytest.raises(RuntimeError,match='播放'):
        edge.play(b'RIFF-test')


# ---- 第1批：树莓派不丢答案、不拿旧答案判新题、播完上报 ----
def _edge(monkeypatch):
    from pi.english_voice import Edge
    monkeypatch.setenv('BRAIN_URL','https://brain.example');monkeypatch.setenv('EDGE_TOKEN','edge-token-1234567890')
    edge=Edge(play_audio=True,start_worker=False)
    calls=[];state={'i':0}
    def request(path,*,body=None,content=None,params=None,raw=False):
        calls.append((path,body))
        if path=='/voice/speech': return b'RIFF'
        if body and body.get('action') in ('played','tick'): return {'active':True,'phase':'listen','session_id':'s','word_index':state['i'],'segments':[]}
        if body and body.get('action')=='answer' and body.get('text')=='???':
            return {'active':True,'phase':'listen','session_id':'s','word_index':state['i'],'segments':[{'text':'Again, please.','language':'en'}]}
        if path=='/voice/audio' or (body and body.get('action')=='answer'): state['i']+=1
        return {'active':True,'phase':'listen','session_id':'s','word_index':state['i'],'segments':[{'text':'banana.','language':'en'}]}
    edge.request=request;edge.play=lambda wav:None;edge.local_message=lambda text:None
    return edge,calls

def test_pi_answer_while_busy_is_queued_not_dropped(monkeypatch):
    edge,calls=_edge(monkeypatch)
    edge.busy=True
    assert edge.submit(wav=b'RIFF-answer') is True
    assert edge.queue.qsize()==1

def test_pi_tick_only_when_fully_idle(monkeypatch):
    edge,calls=_edge(monkeypatch)
    edge.active=True
    edge.busy=True;assert edge.submit_tick() is False
    edge.busy=False;edge.submit(wav=b'RIFF-answer');assert edge.submit_tick() is False
    edge.queue.get_nowait();edge.queue.task_done()
    edge.playing=True;assert edge.submit_tick() is False
    edge.playing=False;assert edge.submit_tick() is True

def test_pi_answer_recorded_before_new_prompt_is_discarded(monkeypatch):
    edge,calls=_edge(monkeypatch)
    edge.submit('start');edge.process(edge.queue.get_nowait());edge.queue.task_done()
    edge.submit(wav=b'RIFF-old')
    old=edge.queue.get_nowait();edge.queue.task_done()
    # 自动重问（tick）不算换题，旧录音仍然有效
    edge.process({'generation':edge.generation,'action':'tick','text':'','wav':None,'request_id':'tick-000001','spoken':edge.spoken})
    assert old['spoken']==edge.spoken
    # 没听清的重问不算换题，旧录音仍然有效
    edge.process({'generation':edge.generation,'action':'answer','text':'???','wav':None,'request_id':'unclear-0001','spoken':edge.spoken})
    assert old['spoken']==edge.spoken
    # 另一个回答让机器人出了新题：之前录的答案不能拿去判新题
    edge.process({'generation':edge.generation,'action':'answer','text':'苹果','wav':None,'request_id':'answer-00001','spoken':edge.spoken})
    calls.clear()
    edge.process(old)
    assert not any(p=='/voice/audio' for p,_ in calls)
    edge.submit(wav=b'RIFF-new');fresh=edge.queue.get_nowait();edge.queue.task_done()
    edge.process(fresh)
    assert any(p=='/voice/audio' for p,_ in calls)

def test_pi_reports_playback_end_after_speaking(monkeypatch):
    edge,calls=_edge(monkeypatch)
    edge.submit('start');edge.process(edge.queue.get_nowait());edge.queue.task_done()
    paths=[(p,(b or {}).get('action')) for p,b in calls]
    assert paths[-2:]==[('/voice/speech',None),('/voice/turn','played')]

def test_pi_dialog_unclear_keeps_queued_answer_but_next_turn_discards_it(monkeypatch):
    from pi.english_voice import Edge
    monkeypatch.setenv('BRAIN_URL','https://brain.example');monkeypatch.setenv('EDGE_TOKEN','edge-token-1234567890')
    edge=Edge(play_audio=True,start_worker=False)
    state={'n':0};calls=[]
    def request(path,*,body=None,content=None,params=None,raw=False):
        calls.append(path)
        if path=='/voice/speech': return b'RIFF'
        base={'active':True,'phase':'dialog','session_id':'s','word_index':2}
        if body and body.get('action') in ('played','tick'): return {**base,'dialog_count':state['n'],'segments':[]}
        if body and body.get('text')=='???':   # 对话阶段没听清：有播报内容，但不是新一轮
            return {**base,'dialog_count':state['n'],'segments':[{'text':'Again, please.','language':'en'}]}
        state['n']+=1
        return {**base,'dialog_count':state['n'],'segments':[{'text':'What else do you like?','language':'en'}]}
    edge.request=request;edge.play=lambda wav:None;edge.local_message=lambda text:None
    edge.process({'generation':edge.generation,'action':'answer','text':'I like apples','wav':None,'request_id':'dlg-000001','spoken':edge.spoken})
    edge.submit(wav=b'RIFF-queued');queued=edge.queue.get_nowait();edge.queue.task_done()
    edge.process({'generation':edge.generation,'action':'answer','text':'???','wav':None,'request_id':'dlg-000002','spoken':edge.spoken})
    assert queued['spoken']==edge.spoken            # 没听清的重问不算换题
    edge.process({'generation':edge.generation,'action':'answer','text':'I like bananas','wav':None,'request_id':'dlg-000003','spoken':edge.spoken})
    calls.clear();edge.process(queued)
    assert '/voice/audio' not in calls              # 对话进入下一轮，旧录音不再送去判


def test_miniprogram_merge_conflicts_fail_before_copy(tmp_path):
    from english_class.sources import merge_miniprogram
    src=tmp_path/'original';src.mkdir()
    (src/'app.json').write_text(json.dumps({'pages':['pages/learn/index']}))
    (src/'utils').mkdir();(src/'utils/page-state.js').write_text('original helper')
    dest=tmp_path/'merged'
    overlay=Path(__file__).resolve().parents[1]/'miniprogram'
    with pytest.raises(ValueError,match='冲突|同名'): merge_miniprogram(src,overlay,dest)
    assert not dest.exists()
    assert (src/'utils/page-state.js').read_text()=='original helper'

def test_miniprogram_standalone_build_has_six_pages_and_no_local_credentials(tmp_path):
    import subprocess,sys
    from fnmatch import fnmatchcase
    root=Path(__file__).resolve().parents[1];out=tmp_path/'standalone'
    result=subprocess.run([sys.executable,str(root/'scripts/build_miniprogram.py'),'--output',str(out)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    source=root/'miniprogram'
    # A default standalone build copies every canonical file byte for byte,
    # excluding only the builder's documented local/private/tool artifacts.
    excluded=('.git','node_modules','__pycache__','.DS_Store','project.private.config.json','*.local.js','.env','.env.*')
    expected={path.relative_to(source) for path in source.rglob('*')
              if path.is_file() and not any(fnmatchcase(part,pattern)
              for part in path.relative_to(source).parts for pattern in excluded)}
    actual={path.relative_to(out) for path in out.rglob('*') if path.is_file()}
    assert actual==expected
    for relative in sorted(expected):
        assert (out/relative).read_bytes()==(source/relative).read_bytes(),str(relative)
    assert len(json.loads((out/'app.json').read_text())['pages'])==6
    assert not (out/'utils/english-env.local.js').exists()
    assert json.loads((out/'project.config.json').read_text())['setting']['urlCheck'] is True
    second=subprocess.run([sys.executable,str(root/'scripts/build_miniprogram.py'),'--output',str(out)],capture_output=True,text=True)
    assert second.returncode!=0


def test_default_vad_ends_speech_after_point_six_seconds():
    """每块 0.1s：默认 6 块静音（0.6s）判定说完，避免孩子说完干等一秒。"""
    from pi.audio import VoiceActivity
    import array
    v = VoiceActivity(threshold=100)
    speech = array.array('h', [1000] * 1600).tobytes()
    assert v.feed(speech) is None
    for _ in range(5):
        assert v.feed(b'\x00' * 3200) is None
    wav = v.feed(b'\x00' * 3200)
    assert wav and wav.startswith(b'RIFF')


def test_wake_word_tolerates_extra_words_before_it():
    """唤醒词可能被 Vosk 多吐字或孩子带语气词，含在句中也要认出来。"""
    from pi.audio import split_wake
    assert split_wake('嗯小陈同学') == (True, '')
    assert split_wake('哎，小陈同学，学英语') == (True, '学英语')
    assert split_wake('今天天气不错') == (False, '今天天气不错')


def test_start_command_tolerates_vosk_homophone_errors():
    """“学英语”被听成同音字时仍要能上课；否定句不能误触发。"""
    from pi.audio import control_action
    assert control_action('小陈同学学英语') == 'start'
    assert control_action('小陈同学，雪英语') == 'start'
    assert control_action('小陈同学学英玉') == 'start'
    assert control_action('学英语') == 'start'
    assert control_action('小陈同学') == 'chat'
    assert control_action('小陈同学我不想学英语') is None
    assert control_action('小陈同学别学英语') is None
