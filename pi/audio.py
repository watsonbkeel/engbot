"""Small audio helpers for the aibot English-course voice addon (16k PCM)."""
from __future__ import annotations
import array
import io
import math
import re
import subprocess
import wave
from collections import deque


# 唤醒词“小陈同学”；Vosk 小模型常把“陈”听成同音字，一并接受。
WAKE_WORDS=('小陈同学','小晨同学','小成同学','小程同学','小辰同学','小橙同学','小沉同学','小尘同学','小臣同学','小城同学','小诚同学','小忱同学')
START_PHRASES=('学英语','开始学英语','我要学英语','我们学英语','开始英语练习','开始今天的英语练习','开始练习')
# 上课意图的兜底关键词：Vosk 常把“英语”听成英玉/因语，逐字精确匹配会整句作废。
START_KEYWORDS=('学英语','上英语课','开始上课','开始学英语','英语课','开始学')
START_EXCLUDES=('不学','别学','不想学','不上','不用学','不要学','怎么说','什么意思','怎么读','单词','翻译')


def split_wake(text:str):
    """返回 (是否含唤醒词, 去掉唤醒词、空格和标点后的剩余文字)。
    用包含匹配而非前缀匹配：孩子常在前面带“嗯/哎”等语气词，Vosk 也会多吐字。"""
    s=re.sub(r'[\s，。！？,.!?、;；:：]','',text.lower())
    for w in WAKE_WORDS:
        i=s.find(w)
        if i>=0: return True,s[i+len(w):]
    return False,s


def is_start_command(s:str,had_wake:bool=False):
    """是否"要上英语课"。先用精确短语，再按关键词兜底，最后对近音字放宽。"""
    if not s or len(s)>12: return False
    if any(x in s for x in START_EXCLUDES): return False
    if s in START_PHRASES: return True
    if any(k in s for k in START_KEYWORDS): return True
    # 近音容错："学"常被听成"雪/学/小/削"，"英语"被听成"英玉/因语/音乐/音语"。
    # 带唤醒词的短句，且以"学/雪/小"开头时，只要包含"英/语/音/乐"就匹配。
    if had_wake and len(s)<=6 and s and s[0] in '学雪小削':
        return '英' in s or '语' in s or '音' in s or '乐' in s
    return False


def control_action(text:str):
    """两种进入方式：“小陈同学，学英语”=上英语课(start)；只说“小陈同学”=找原机器人聊天(chat)。"""
    had_wake,s=split_wake(text)
    if had_wake and not s: return 'chat'
    if is_start_command(s,had_wake): return 'start'
    return {'结束':'stop','结束练习':'stop','停止练习':'stop','iwanttostop':'stop','暂停':'pause','暂停练习':'pause','继续':'resume',
            '继续练习':'resume','再说一次':'repeat','再读一次':'repeat','慢一点':'slow','说慢一点':'slow',
            '听不懂':'explain','什么意思':'explain','这是什么意思':'explain','这个词什么意思':'explain',
            '用中文解释':'explain','给我提示':'explain',
            '我不会':'howtosay','怎么说':'howtosay','不会说':'howtosay','我不会说':'howtosay'}.get(s)


def wav_bytes(pcm:bytes):
    f=io.BytesIO()
    with wave.open(f,'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(pcm)
    return f.getvalue()


def amplify(pcm:bytes,gain:float) -> bytes:
    if gain==1: return pcm
    a=array.array('h');a.frombytes(pcm)
    return array.array('h',(max(-32768,min(32767,int(v*gain))) for v in a)).tobytes()

class VoiceActivity:
    # 每块 0.1s：6 块静音=0.6s 判定"说完了"（原 10 块=1.0s，延迟诊断后收紧）。
    # 孩子句尾停顿通常 <0.5s；若实测误截断，调到 7-8。
    def __init__(self,threshold=450,silence_chunks=6,max_chunks=180,log=None):
        self.threshold=threshold;self.silence_chunks=silence_chunks;self.max_chunks=max_chunks
        self.log=log or (lambda *a,**k:None)
        self.reset()
    def reset(self):
        self.parts=[];self.before=deque(maxlen=3);self.silence=0;self.speech_start=None
    def feed(self,chunk:bytes):
        import time
        a=array.array('h');a.frombytes(chunk[:len(chunk)//2*2])
        rms=math.sqrt(sum(v*v for v in a)/max(1,len(a)))
        voice=rms>=self.threshold
        if not self.parts:
            if not voice: self.before.append(chunk);return None
            self.parts=list(self.before);self.before.clear()
            self.speech_start=time.monotonic()
            self.log('VAD: 检测到语音开始 rms=%.0f', rms)
        self.parts.append(chunk)
        self.silence=0 if voice else self.silence+1
        # 每 0.3s（3 块）打一次静音计数，避免刷屏
        if self.silence>0 and self.silence%3==0:
            dur=time.monotonic()-self.speech_start if self.speech_start else 0
            self.log('VAD: 累计静音 %d/6 块，已录 %.1fs', self.silence, dur)
        if self.silence>=self.silence_chunks or len(self.parts)>=self.max_chunks:
            dur=time.monotonic()-self.speech_start if self.speech_start else 0
            self.log('VAD: 判定说完 总时长=%.1fs 静音块=%d/%d', dur, self.silence, self.silence_chunks)
            pcm=b''.join(self.parts);self.reset();return wav_bytes(pcm)
        return None


def find_usb_mic() -> str:
    """Stable ALSA CARD names, following the existing aibot USB-audio convention."""
    result=subprocess.run(['arecord','-l'],capture_output=True,text=True,timeout=10)
    for line in result.stdout.splitlines():
        if 'USB' not in line and 'usb' not in line: continue
        match=re.search(r'card\s+\d+:\s*([^\s]+).*device\s+(\d+):',line)
        if match: return f'plughw:CARD={match.group(1)},DEV={match.group(2)}'
    raise RuntimeError('未找到USB麦克风；运行arecord -l，或设置CAPTURE_DEVICE')
