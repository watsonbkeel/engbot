"""Single public SQLite owner; student applications never open this database."""
from __future__ import annotations
import hashlib
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from .dictionary import Dictionary
from .models import LearningConfig, LessonRecordInput
from .migrations import migrate, migration_lock
from .secret_store import private_directory, secure_database_files

class Conflict(ValueError):
    pass

class RateLimit(ValueError):
    pass

# 每次练习的附加证据 → 累计次数字段。只用于展示“回答有效/用了目标词/模仿跟读”，不影响 status 规则。
EVIDENCE_COLUMNS={'answer_valid':'valid_count','used_word':'used_word_count','imitated':'imitated_count'}

def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

class Store:
    def __init__(self, path: str | Path, dictionary: Dictionary, timezone: str = 'Asia/Shanghai',
                 credential_key_path: str | Path | None = None):
        self.path = Path(path)
        self.credential_key_path = Path(credential_key_path or os.environ.get('LLM_SECRET_KEY_FILE') or str(self.path) + '.key')
        private_directory(self.path.parent)
        self.dictionary = dictionary
        self.timezone = ZoneInfo(timezone)
        with migration_lock(self.path):
            secure_database_files(self.path)
            with self.connect() as con:
                self._credential_cipher = migrate(con, self.credential_key_path)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=15)
        try:
            con.row_factory = sqlite3.Row
            con.execute('PRAGMA foreign_keys=ON')
            con.execute('PRAGMA busy_timeout=15000')
            con.execute('PRAGMA secure_delete=ON')
            with con:
                yield con
        finally:
            con.close()

    def add_student(self, student_id: str, parent_token: str, brain_token: str):
        if not re.fullmatch(r'[a-z][a-z0-9_-]{1,31}', student_id):
            raise ValueError('学生ID使用2—32位小写字母、数字、下划线或短横线，首位为字母')
        if min(len(parent_token), len(brain_token)) < 16 or parent_token == brain_token:
            raise ValueError('parent/brain 必须使用不同的、至少16位随机凭证')
        g,s = sorted(self.dictionary.terms)[0]
        cfg = LearningConfig(grade=g, semester=s).model_dump_json()
        try:
            with self.connect() as con:
                con.execute('INSERT INTO students(id,config) VALUES (?,?)', (student_id,cfg))
                con.executemany('INSERT INTO credentials VALUES (?,?,?)',[(token_hash(parent_token),student_id,'parent'),(token_hash(brain_token),student_id,'brain')])
        except sqlite3.IntegrityError as exc:
            raise ValueError('学生ID或凭证已经存在；未覆盖原有数据') from exc

    def authenticate(self, token: str):
        with self.connect() as con:
            row=con.execute('SELECT student_id,role FROM credentials WHERE hash=?',(token_hash(token),)).fetchone()
        return dict(row) if row else None

    def config(self, student_id: str) -> dict:
        with self.connect() as con:
            row=con.execute('SELECT config FROM students WHERE id=?',(student_id,)).fetchone()
        if row is None: raise ValueError('学生不存在')
        return LearningConfig.model_validate(json.loads(row['config'])).model_dump()

    def save_config(self, student_id: str, config: dict) -> dict:
        obj=LearningConfig.model_validate(config)
        self.dictionary.select(obj.grade,obj.semester,obj.unit)
        with self.connect() as con:
            cur=con.execute('UPDATE students SET config=? WHERE id=?',(obj.model_dump_json(),student_id))
            if not cur.rowcount: raise ValueError('学生不存在')
        return obj.model_dump()

    # 学生自带大模型。密钥只在服务端使用，接口永不回传明文。
    def llm(self, student_id: str) -> dict | None:
        with self.connect() as con:
            row=con.execute('SELECT * FROM student_llm WHERE student_id=?',(student_id,)).fetchone()
        if not row: return None
        result=dict(row); result['thinking']=bool(result['thinking'])
        result['allow_platform_fallback']=bool(result['allow_platform_fallback'])
        result['api_key']=self._credential_cipher.decrypt(student_id, result['api_key'])
        return result

    def save_llm(self, student_id: str, base_url: str, model: str, api_key: str, thinking: bool=False,
                 allow_platform_fallback: bool=False):
        now=datetime.now(self.timezone).isoformat(timespec='seconds')
        encrypted=self._credential_cipher.encrypt(student_id, api_key)
        with self.connect() as con:
            con.execute('''INSERT INTO student_llm(student_id,base_url,model,api_key,updated_at,last_status,last_error,last_used_at,thinking,allow_platform_fallback) VALUES (?,?,?,?,?,'ok','',?,?,?)
            ON CONFLICT(student_id) DO UPDATE SET base_url=excluded.base_url,model=excluded.model,api_key=excluded.api_key,updated_at=excluded.updated_at,last_status='ok',last_error='',last_used_at=excluded.last_used_at,thinking=excluded.thinking,allow_platform_fallback=excluded.allow_platform_fallback''',
                        (student_id,base_url,model,encrypted,now,now,int(thinking),int(allow_platform_fallback)))

    def clear_llm(self, student_id: str):
        with self.connect() as con: con.execute('DELETE FROM student_llm WHERE student_id=?',(student_id,))

    def mark_llm(self, student_id: str, status: str, error: str = ''):
        now=datetime.now(self.timezone).isoformat(timespec='seconds')
        with self.connect() as con:
            con.execute('UPDATE student_llm SET last_status=?,last_error=?,last_used_at=? WHERE student_id=?',(status,error[:200],now,student_id))

    def today(self) -> str:
        return datetime.now(self.timezone).date().isoformat()

    def student_ids(self) -> list[str]:
        with self.connect() as con: return [r['id'] for r in con.execute('SELECT id FROM students')]

    def status(self,student_id:str) -> dict:
        with self.connect() as con:
            row=con.execute('SELECT pi_last_seen,brain_last_seen,pi_ssh_ok,pi_ssh_checked_at FROM students WHERE id=?',(student_id,)).fetchone()
        if row is None: raise ValueError('学生不存在')
        item=dict(row)
        if item['pi_ssh_ok'] is not None: item['pi_ssh_ok']=bool(item['pi_ssh_ok'])
        return {**item,'server_time':datetime.now(self.timezone).isoformat(timespec='seconds')}

    def heartbeat(self,student_id:str,pi:bool=False) -> dict:
        now=datetime.now(self.timezone).isoformat(timespec='seconds')
        with self.connect() as con:
            if pi:
                cur=con.execute('UPDATE students SET brain_last_seen=?,pi_last_seen=? WHERE id=?',(now,now,student_id))
            else: cur=con.execute('UPDATE students SET brain_last_seen=? WHERE id=?',(now,student_id))
            if not cur.rowcount: raise ValueError('学生不存在')
        return self.status(student_id)

    def mark_pi_ssh(self,student_id:str,ok:bool):
        with self.connect() as con:
            con.execute('UPDATE students SET pi_ssh_ok=?,pi_ssh_checked_at=? WHERE id=?',
                        (int(ok),datetime.now(self.timezone).isoformat(timespec='seconds'),student_id))

    def reserve_scene_generation(self,student_id:str,limit:int=20) -> str:
        day=self.today()
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row=con.execute('SELECT count FROM scene_generation_usage WHERE student_id=? AND day=?',(student_id,day)).fetchone()
            if row and row['count']>=limit: raise RateLimit(f'今天已请求{limit}次场景（包含失败尝试），请明天再试，也可以手动填写')
            con.execute('INSERT INTO scene_generation_usage(student_id,day,count) VALUES (?,?,1) ON CONFLICT(student_id,day) DO UPDATE SET count=count+1',(student_id,day))
            # Keep yesterday until requests started just before midnight have
            # returned; their success belongs to the reserved day's attempts.
            oldest=(date.fromisoformat(day)-timedelta(days=1)).isoformat()
            con.execute('DELETE FROM scene_generation_usage WHERE day<?',(oldest,))
        return day

    def mark_scene_generation_success(self,student_id:str,day:str):
        with self.connect() as con:
            result=con.execute('UPDATE scene_generation_usage SET success_count=success_count+1 WHERE student_id=? AND day=? AND success_count<count',(student_id,day))
            if result.rowcount!=1: raise Conflict('场景生成次数记录不匹配，未增加成功次数')

    def scene_generation_usage(self,student_id:str,limit:int=20) -> dict:
        day=self.today()
        with self.connect() as con:
            row=con.execute('SELECT count,success_count FROM scene_generation_usage WHERE student_id=? AND day=?',(student_id,day)).fetchone()
        attempts=row['count'] if row else 0
        return {'day':day,'attempts':attempts,'successes':row['success_count'] if row else 0,
                'limit':limit,'remaining':max(0,limit-attempts),'successes_since_version':'0.3.4'}

    def _decorate(self,row) -> dict:
        item=dict(row)
        item.pop('student_id',None);item.pop('updated_at',None)
        word=self.dictionary.by_id.get(item['word_id'],{})
        item.update(word=word.get('word',item['word_id']), meaning=word.get('meaning',''))
        return item

    def lessons(self, student_id: str, limit: int = 100) -> list[dict]:
        limit = min(100, max(1, int(limit)))
        with self.connect() as con:
            rows = con.execute('SELECT session_id,revision,started_at,ended_at,day,payload FROM lessons WHERE student_id=? ORDER BY started_at DESC LIMIT ?', (student_id, limit)).fetchall()
        result=[]
        for row in rows:
            item=json.loads(row['payload'])
            item['session_id']=row['session_id']; item['revision']=row['revision']; item['started_at']=row['started_at']; item['ended_at']=row['ended_at']; item['day']=row['day']
            result.append(item)
        return result

    def record_lesson(self, student_id: str, payload: dict) -> dict:
        obj = LessonRecordInput.model_validate(payload)
        data = obj.model_dump(mode='json')
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        fingerprint = hashlib.sha256(raw.encode()).hexdigest()
        day = obj.started_at.astimezone(self.timezone).date().isoformat()
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            prior = con.execute('SELECT * FROM lessons WHERE student_id=? AND session_id=?', (student_id, obj.session_id)).fetchone()
            if prior:
                if obj.revision < prior['revision']:
                    return self._lesson_row(prior)
                if obj.revision == prior['revision']:
                    if prior['fingerprint'] != fingerprint: raise Conflict('同一课堂版本内容冲突')
                    return self._lesson_row(prior)
                old = json.loads(prior['payload'])
                immutable = ('started_at', 'mode', 'scene_name')
                if any(data[name] != old.get(name) for name in immutable):
                    raise Conflict('课堂版本不能修改开始时间、模式或场景')
                if old.get('status') != 'in_progress' and obj.status != old.get('status'):
                    raise Conflict('已结束课堂不能修改关闭状态')
                if old.get('status') == 'in_progress' and obj.status == 'in_progress' and obj.ended_at is not None:
                    raise Conflict('进行中课堂不能关闭')
            con.execute('''INSERT INTO lessons(student_id,session_id,revision,started_at,ended_at,day,payload,fingerprint) VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(student_id,session_id) DO UPDATE SET revision=excluded.revision,started_at=excluded.started_at,ended_at=excluded.ended_at,day=excluded.day,payload=excluded.payload,fingerprint=excluded.fingerprint''',
                (student_id,obj.session_id,obj.revision,obj.started_at.isoformat(),obj.ended_at.isoformat() if obj.ended_at else None,day,raw,fingerprint))
            row=con.execute('SELECT * FROM lessons WHERE student_id=? AND session_id=?',(student_id,obj.session_id)).fetchone()
        return self._lesson_row(row)

    @staticmethod
    def _lesson_row(row):
        item=json.loads(row['payload']); item.update(session_id=row['session_id'], revision=row['revision'], started_at=row['started_at'], ended_at=row['ended_at'], day=row['day']); return item

    def progress(self,student_id: str) -> dict:
        with self.connect() as con:
            rows=con.execute('SELECT * FROM progress WHERE student_id=? ORDER BY updated_at DESC, word_id',(student_id,)).fetchall()
        return {'today':self.today(),'words':[self._decorate(r) for r in rows], 'lessons': self.lessons(student_id)}

    def record(self,student_id: str,word_id: str,status: int | None,unclear: bool,event_key: str | None=None,evidence: dict | None=None) -> dict:
        if word_id not in self.dictionary.by_id:
            raise ValueError('未知的词库word_id')
        if status is not None and (type(status) is not int or status not in (0,1,2)):
            raise ValueError('status只能为0/1/2/null')
        if type(unclear) is not bool or (unclear and status is not None):
            raise ValueError('没听清时不得更新状态')
        if event_key is not None and not 1<=len(event_key)<=128:
            raise ValueError('无效事件编号')
        evidence=evidence or {}
        if set(evidence)-set(EVIDENCE_COLUMNS) or any(type(v) is not bool for v in evidence.values()):
            raise ValueError('evidence只能包含answer_valid/used_word/imitated布尔值')
        if unclear and any(evidence.values()): raise ValueError('没听清时不得记录回答证据')
        inc=[int(evidence.get(k,False)) for k in EVIDENCE_COLUMNS]
        # 不带 evidence 的旧请求指纹保持不变，重放兼容。
        fingerprint=hashlib.sha256(json.dumps([word_id,status,unclear]+([inc] if evidence else [])).encode()).hexdigest()
        now=datetime.now(self.timezone)
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            if event_key:
                prior=con.execute('SELECT fingerprint,result FROM events WHERE student_id=? AND event_key=?',(student_id,event_key)).fetchone()
                if prior:
                    if prior['fingerprint']!=fingerprint: raise Conflict('同一请求编号不能提交不同结果')
                    return json.loads(prior['result'])
            con.execute('''INSERT INTO progress(student_id,word_id,status,unclear_count,last_practiced_date,updated_at,valid_count,used_word_count,imitated_count) VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(student_id,word_id) DO UPDATE SET status=MAX(progress.status,excluded.status), unclear_count=progress.unclear_count+excluded.unclear_count,last_practiced_date=excluded.last_practiced_date,updated_at=excluded.updated_at,
            valid_count=progress.valid_count+excluded.valid_count,used_word_count=progress.used_word_count+excluded.used_word_count,imitated_count=progress.imitated_count+excluded.imitated_count''',
                        (student_id,word_id,status or 0,int(unclear),now.date().isoformat(),now.isoformat(),*inc))
            row=con.execute('SELECT * FROM progress WHERE student_id=? AND word_id=?',(student_id,word_id)).fetchone()
            result=self._decorate(row)
            if event_key: con.execute('INSERT INTO events VALUES (?,?,?,?)',(student_id,event_key,fingerprint,json.dumps(result,ensure_ascii=False)))
        return result
