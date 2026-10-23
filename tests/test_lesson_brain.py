"""Offline end-to-end lesson recording and safe review diagnostics."""
import copy
import json

import pytest
from fastapi.testclient import TestClient

from english_class.brain_api import create_brain
from english_class.client import ServiceError
from english_class.engine import Tutor
from test_v3_learning import V3IO, SCENE
from test_v3_reliability import HEADERS, EDGE_TOKEN, turn


class LessonIO(V3IO):
    def __init__(self, db):
        super().__init__(mode='scene', count=1, scene=SCENE)
        self.db=db
        self.record_failures=0
        self.start_failures=0
        self.review_raw=None
        self.dialog_reply='Thank you.'

    async def record_lesson(self, payload):
        result=self.db.record_lesson('s001',payload)
        if self.record_failures:
            self.record_failures-=1
            raise ServiceError('test: response lost after commit')
        return result

    async def config(self):
        if self.start_failures:
            self.start_failures-=1
            raise ServiceError('test: start failed')
        return await super().config()

    async def chat(self,messages,json_output=True):
        if 'SCENE_REVIEW' in messages[0]['content'] and self.review_raw is not None:
            self.chat_calls.append(copy.deepcopy(messages))
            return self.review_raw
        return await super().chat(messages,json_output)


@pytest.fixture
def lesson_io(db):
    db.add_student('s001','lesson-parent-token-123456','lesson-brain-token-1234567')
    return LessonIO(db)


def test_scene_without_target_word_and_failed_review_still_records(lesson_io,tmp_path):
    lesson_io.review_raw=json.dumps({'praise':'Good effort.','tips':['x'*41]})
    with TestClient(create_brain(lesson_io,EDGE_TOKEN,state_path=tmp_path/'resume.json')) as client:
        start=turn(client,'start').json()
        assert lesson_io.db.lessons('s001')[0]['status']=='in_progress'
        assert turn(client,text='Hi, sir',identity=start).status_code==200
        response=turn(client,text='Thank you.',request_id='scene-answer-no-target')
        assert response.status_code==200
        result=turn(client,'stop',request_id='lesson-stop-failed-review')
        assert result.status_code==200 and not result.json()['active']
        assert '点评暂时无法生成' in ' '.join(s['text'] for s in result.json()['segments'])
        calls=len(lesson_io.chat_calls)
        assert turn(client,'stop',request_id='lesson-stop-failed-review').json()==result.json()
        assert len(lesson_io.chat_calls)==calls
    rows=lesson_io.db.lessons('s001')
    assert len(rows)==1 and rows[0]['status']=='stopped'
    assert rows[0]['review_status']=='failed' and rows[0]['review_error']=='ReviewTipsInvalid'
    assert rows[0]['dialog_count']==1 and rows[0]['review_segments']==[]
    assert lesson_io.db.progress('s001')['words']==[]


def test_lost_end_record_reply_survives_restart_without_second_review(lesson_io,tmp_path):
    state=tmp_path/'resume.json'
    with TestClient(create_brain(lesson_io,EDGE_TOKEN,state_path=state)) as client:
        assert turn(client,'start').status_code==200
        assert turn(client,text='Hi, sir').status_code==200
        lesson_io.record_failures=1
        fail=turn(client,'stop',request_id='lost-end-record-reply')
        assert fail.status_code==503
        calls=len(lesson_io.chat_calls)
        stored=copy.deepcopy(lesson_io.db.lessons('s001')[0])
        assert stored['status']=='stopped' and stored['review_status']=='success'
    with TestClient(create_brain(lesson_io,EDGE_TOKEN,state_path=state)) as client:
        recovered=turn(client,'stop',request_id='lost-end-record-reply')
        assert recovered.status_code==200
        assert len(lesson_io.chat_calls)==calls
        assert lesson_io.db.lessons('s001')[0]==stored
        assert turn(client,'stop',request_id='lost-end-record-reply').json()==recovered.json()


def test_failed_provider_and_lost_record_reply_never_retries_review(lesson_io,tmp_path):
    state=tmp_path/'resume.json'
    lesson_io.review_fail=True
    with TestClient(create_brain(lesson_io,EDGE_TOKEN,state_path=state)) as client:
        assert turn(client,'start').status_code==200
        lesson_io.record_failures=1
        assert turn(client,'stop',request_id='failed-review-lost-record').status_code==503
        calls=len(lesson_io.chat_calls)
    with TestClient(create_brain(lesson_io,EDGE_TOKEN,state_path=state)) as client:
        assert turn(client,'stop',request_id='failed-review-lost-record').status_code==200
        assert len(lesson_io.chat_calls)==calls
        row=lesson_io.db.lessons('s001')[0]
        assert row['review_status']=='failed' and row['review_error']=='ReviewProviderFailed'


def test_lost_start_reply_does_not_create_second_lesson(lesson_io,tmp_path):
    state=tmp_path/'resume.json';lesson_io.record_failures=1
    with TestClient(create_brain(lesson_io,EDGE_TOKEN,state_path=state)) as client:
        assert turn(client,'start',request_id='lost-start-record-reply').status_code==503
        first=copy.deepcopy(lesson_io.db.lessons('s001')[0])
    with TestClient(create_brain(lesson_io,EDGE_TOKEN,state_path=state)) as client:
        start=turn(client,'start',request_id='lost-start-record-reply')
        assert start.status_code==200
        assert len(lesson_io.db.lessons('s001'))==1
        assert start.json()['session_id']==first['session_id']
        assert lesson_io.db.lessons('s001')[0]==first
        assert turn(client,'stop').status_code==200


@pytest.mark.parametrize('raw,code',[
    ('not json','ReviewJsonInvalid'),
    (json.dumps({'praise':'','tips':[]}),'ReviewPraiseInvalid'),
    (json.dumps({'praise':'Nice.','tips':{}}),'ReviewTipsInvalid'),
    (json.dumps({'praise':'Nice.','tips':[None]}),'ReviewTipsInvalid'),
])
def test_review_error_categories_do_not_log_raw_model_text(lesson_io,raw,code,caplog):
    lesson_io.review_raw=raw
    tutor=Tutor(lesson_io)
    import asyncio
    async def run():
        await tutor.turn(action='start')
        return await tutor.end_lesson()
    result=asyncio.run(run())
    assert result['phase']=='done'
    assert tutor.review_error==code and tutor.review_status=='failed'
    assert code in caplog.text
    assert raw not in caplog.text


def test_review_provider_failure_still_closes(lesson_io):
    lesson_io.review_fail=True
    tutor=Tutor(lesson_io)
    import asyncio
    async def run():
        await tutor.turn(action='start')
        return await tutor.end_lesson()
    assert asyncio.run(run())['phase']=='done'
    assert tutor.review_error=='ReviewProviderFailed'


def test_auto_finished_scene_records_success_without_vocabulary(lesson_io,tmp_path):
    with TestClient(create_brain(lesson_io,EDGE_TOKEN,state_path=tmp_path/'resume.json')) as client:
        assert turn(client,'start').status_code==200
        assert turn(client,text='Hi, sir').status_code==200
        for index in range(6):
            reply=turn(client,text='Thank you.',request_id=f'auto-close-answer-{index:02d}')
            assert reply.status_code==200
        assert not reply.json()['active']
        row=lesson_io.db.lessons('s001')[0]
        assert row['status']=='completed' and row['review_status']=='success'
        assert row['dialog_count']==6 and row['review_segments']
        assert lesson_io.db.progress('s001')['words']==[]


def test_word_only_lesson_records_without_ai_review(lesson_io,tmp_path):
    lesson_io.config_value.update(mode='en2zh',scene=None)
    with TestClient(create_brain(lesson_io,EDGE_TOKEN,state_path=tmp_path/'resume.json')) as client:
        assert turn(client,'start').status_code==200
        response=turn(client,text='苹果')
        assert response.status_code==200 and not response.json()['active']
        row=lesson_io.db.lessons('s001')[0]
        assert row['status']=='completed' and row['review_status']=='not_applicable'
        assert not any('SCENE_REVIEW' in x[0]['content'] for x in lesson_io.chat_calls)


def test_review_english_setting_records_specific_failure(lesson_io,tmp_path):
    lesson_io.config_value['chinese_help']=False
    lesson_io.review_raw=json.dumps({'praise':'你努力了','tips':[]})
    with TestClient(create_brain(lesson_io,EDGE_TOKEN,state_path=tmp_path/'resume.json')) as client:
        assert turn(client,'start').status_code==200
        assert turn(client,'stop').status_code==200
        row=lesson_io.db.lessons('s001')[0]
        assert row['review_error']=='ReviewLanguageInvalid'
        assert row['review_status']=='failed'


def test_new_start_closes_previous_lesson_without_review_call(lesson_io,tmp_path):
    with TestClient(create_brain(lesson_io,EDGE_TOKEN,state_path=tmp_path/'resume.json')) as client:
        assert turn(client,'start',request_id='first-lesson-start').status_code==200
        assert turn(client,'start',request_id='second-lesson-start').status_code==200
        rows=lesson_io.db.lessons('s001')
        assert len(rows)==2
        assert sorted(r['status'] for r in rows)==['in_progress','stopped']
        assert not lesson_io.chat_calls
        assert turn(client,'stop').status_code==200
