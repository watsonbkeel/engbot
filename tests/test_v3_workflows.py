"""Release-level journeys with the bundled original vocabulary and real HTTP.

The upstream model is an explicit fixture; this verifies contracts and state
transitions, not real model quality or microphone recognition.
"""
import json
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Request

from english_class.brain_api import create_brain
from english_class.client import PublicClient
from english_class.dictionary import Dictionary
from english_class.providers import Providers
from english_class.public_api import create_app
from english_class.store import Store
from tests.test_http_integration import running

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('mode',['full','en2zh','zh2en','scene'])
def test_original_dictionary_complete_mode_journey(tmp_path,mode):
    dictionary=Dictionary(ROOT/'data/dictionary.json')
    assert len(dictionary.rows)==3919
    store=Store(tmp_path/'journey.sqlite3',dictionary)
    store.add_student('s001','parent-journey-fixture','brain-journey-fixture')
    upstream=FastAPI();calls=[]
    @upstream.post('/chat/completions')
    async def model(request:Request):
        payload=await request.json();calls.append(payload)
        system=payload['messages'][0]['content']
        data=json.loads(payload['messages'][-1]['content'])
        if 'VOCABULARY_JUDGE' in system:
            result={'correct':data['answer'] in (data['word'],data['meaning'])}
        elif 'SCENE_REVIEW' in system:
            result={'praise':'You kept the conversation going.','tips':['Try a longer answer next time.']}
        else:
            words=data['target_words'];said=data['answer'] or ''
            result={'reply':[{'text':'Thank you. We have finished our task.' if data['closing'] else 'What would you like to say next?', 'language':'en'}],
                    'relevant':bool(said),'modelled':[],
                    'word_evidence':[{'word_id':w['word_id'],'correct':True,'independent':True} for w in words if w['word'].lower() in said.lower().split()]}
        return {'choices':[{'message':{'content':json.dumps(result)}}]}
    with running(upstream) as provider_url:
        provider=Providers(llm_base=provider_url,llm_key='journey-test-only')
        with running(create_app(store,provider)) as public_url:
            io=PublicClient(public_url,'s001','brain-journey-fixture')
            brain=create_brain(io,'edge-journey-fixture',state_path=tmp_path/'state/resume.json')
            with running(brain) as brain_url, httpx.Client(timeout=10) as client:
                parent={'Authorization':'Bearer parent-journey-fixture'}
                edge={'Authorization':'Bearer edge-journey-fixture'}
                query={'student_id':'s001'}
                cfg=client.get(public_url+'/api/config',headers=parent,params=query).json()
                cfg.update(mode=mode,practice_words=2)
                if mode=='scene':
                    cfg['scene']={'name':'Greetings','robot_role':'friendly guide','student_role':'visitor',
                                  'goal':'Say hello, choose a place and end politely.','opening':'Hello, guide!'}
                saved=client.put(public_url+'/api/config',headers=parent,params=query,json=cfg)
                assert saved.status_code==200,saved.text
                current=None
                def turn(text='',action='answer'):
                    nonlocal current
                    body={'request_id':uuid.uuid4().hex,'action':action,'text':text}
                    if action=='answer' and current:
                        body.update({k:current[k] for k in ('session_id','question_id')})
                    response=client.post(brain_url+'/voice/turn',headers=edge,json=body)
                    assert response.status_code==200,response.text
                    current=response.json()
                    return current
                turn(action='start')
                words=brain.state.tutor.words
                assert len(words)==2 and all(w['word_id'] in dictionary.by_id for w in words)
                if mode in ('full','en2zh'):
                    for word in words: turn(word['meaning'])
                if mode in ('full','zh2en'):
                    for word in words: turn(word['word'])
                if mode=='scene': turn('Hello, guide!')
                if mode in ('full','scene'):
                    limit=6 if mode=='scene' else 4
                    for i in range(limit): turn('hello friend' if i%2==0 else 'hi there')
                    assert current['dialog_count']==limit
                    assert any('finished our task' in s['text'] for s in current['segments'])
                assert current['phase']=='done' and current['active'] is False
                progress=client.get(public_url+'/api/progress',headers=parent,params=query).json()
                assert len(progress['words'])==2
                if mode=='en2zh': assert all(w['status']==1 for w in progress['words'])
                if mode in ('full','zh2en'): assert all(w['status']==2 for w in progress['words'])
                persisted=Store(tmp_path/'journey.sqlite3',dictionary).progress('s001')
                assert persisted==progress
                # The deployed manifest points to real bundled MP3s, protected by parent auth.
                listing=client.get(public_url+'/api/listening',headers=parent,params={**query,'grade':1})
                assert listing.status_code==200 and len(listing.json()['items'])>=5
                path=listing.json()['items'][0]['audio_url']
                assert client.get(public_url+path,params=query).status_code==401
                audio=client.get(public_url+path,headers=parent,params=query)
                assert audio.status_code==200 and audio.headers['content-type']=='audio/mpeg'
                assert len(audio.content)>100_000
    assert calls and all(call['thinking']=={'type':'disabled'} for call in calls)
