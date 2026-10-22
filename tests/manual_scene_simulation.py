"""Manual, test-only GPT actor bridge for the real scene-design journey.

Run with --directory <scratch evidence directory> --cases <cases.json>.
A GPT actor reads inbox/*.json and writes the requested JSON to outbox with
the same filename. This is NOT a production provider or an external API test.
Only the provider boundary is substituted; public/brain HTTP, config, scene
validation, dialogue state, support actions and SQLite remain real.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

from english_class import public_api
from english_class.brain_api import create_brain
from english_class.client import PublicClient
from english_class.dictionary import Dictionary
from english_class.providers import ProviderError
from english_class.store import Store
from tests.test_http_integration import running

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


class ActorBridge:
    def __init__(self, directory):
        self.directory = directory
        self.lock = threading.Lock()
        self.counter = 0
        for name in ('inbox', 'outbox', 'transcripts'):
            (directory / name).mkdir(parents=True, exist_ok=True)

    def issue(self, case_id, kind, payload):
        with self.lock:
            self.counter += 1
            name = f'{self.counter:04d}-{case_id}-{kind}.json'
        request = {'id': name, 'case_id': case_id, 'kind': kind, **payload}
        write_json(self.directory / 'inbox' / name, request)
        print('WAIT', name, flush=True)
        return name

    def answer(self, name):
        path = self.directory / 'outbox' / name
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
        return None

    def learner(self, case, scene, transcript, instruction):
        name = self.issue(case['id'], 'learner', {
            'case': case, 'scene': scene, 'transcript': transcript,
            'instruction': instruction,
            'response_format': {'text': 'one natural learner utterance only', 'note': 'brief description of the intended probe'},
        })
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            response = self.answer(name)
            if response is not None:
                assert isinstance(response.get('text'), str) and response['text'].strip()
                return response
            time.sleep(.2)
        raise TimeoutError(f'GPT learner did not answer {name}')


class GPTActorProviders:
    """Explicit local replacement; real provider serialization is tested separately."""
    llm_model = 'NO_PLATFORM_MODEL_IN_THIS_SIMULATION'

    def __init__(self, bridge):
        self.bridge = bridge

    async def check_llm_url_async(self, url, **kwargs):
        # Dummy .invalid endpoint is accepted ONLY inside this manual test.
        assert url == 'https://gpt-actor.invalid/v1'
        return url

    async def chat(self, messages, json_output=False, llm=None, timeout=45):
        if llm is None:
            raise ProviderError('No platform fixture: this journey must use the student model configuration')
        case_id = llm['model']
        system = messages[0]['content']
        task = next((tag for tag in ('SCENE_REVIEW', 'TUTOR_HOWTOSAY', 'TUTOR_EXPLAIN', 'VOCABULARY_JUDGE') if tag in system), 'SCENE_GENERATE' if 'scene card' in system else 'SCENE_DIALOGUE')
        if task == 'VOCABULARY_JUDGE':
            # This tiny settings probe is a declared fixture. Scene and dialogue
            # language below are generated live by a GPT actor, not by fixtures.
            name = self.bridge.issue(case_id, 'probe_fixture', {'task': task, 'messages': messages, 'json_output': json_output})
            result = {'correct': True}
            write_json(self.bridge.directory / 'outbox' / name, result)
            return json.dumps(result)
        name = self.bridge.issue(case_id, 'model', {
            'task': task, 'messages': messages, 'json_output': json_output,
            'requested_timeout_seconds': timeout,
            'routing': {'base_url': llm['base_url'], 'model': case_id, 'thinking': llm['thinking'], 'api_key': '[test-only key, omitted]'},
            'instruction': 'Act as the requested model. Follow these exact actual product messages; do not repair their design, add audit advice, or use the separate learner instructions. Write the requested JSON object directly.',
        })
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            result = self.bridge.answer(name)
            if result is not None:
                return json.dumps(result, ensure_ascii=False)
            await asyncio.sleep(.2)
        raise ProviderError(f'GPT actor did not answer {name}')


def run_case(case, public_url, bridge, directory):
    case_id = case['id']
    parent = {'Authorization': f'Bearer parent-simulation-{case_id}'}
    edge = {'Authorization': f'Bearer edge-simulation-{case_id}'}
    query = {'student_id': case_id}
    evidence = {'case': case, 'scope': 'Real local public/brain HTTP; GPT file actor at provider boundary; no microphone, external provider, or latency verification', 'steps': []}
    path = directory / 'transcripts' / f'{case_id}.json'
    transcript = []

    def save():
        evidence['transcript'] = transcript
        write_json(path, evidence)

    def checked(response, label):
        evidence['steps'].append({'step': label, 'status': response.status_code})
        assert response.status_code == 200, (label, response.status_code, response.text)
        return response.json()

    try:
        with httpx.Client(timeout=900) as client:
            settings = checked(client.put(public_url + '/api/llm', headers=parent, params=query, json={
                'base_url': 'https://gpt-actor.invalid/v1', 'model': case_id,
                'api_key': f'fake-local-simulation-{case_id}', 'thinking': False,
            }), 'Save own model settings (declared local probe)')
            assert settings['mode'] == 'custom'
            scene = checked(client.post(public_url + '/api/scene/generate', headers=parent, params=query,
                                        json={'description': case['description'], 'grade': case['grade']}), 'Generate actual scene card')
            evidence['scene'] = scene
            cfg = checked(client.get(public_url + '/api/config', headers=parent, params=query), 'Read config')
            cfg.update(grade=case['grade'], difficulty=case['difficulty'], chinese_help=case['chinese_help'],
                       mode='scene', practice_words=3, scene=scene)
            checked(client.put(public_url + '/api/config', headers=parent, params=query, json=cfg), 'Save generated scene and select scene mode')
            io = PublicClient(public_url, case_id, f'brain-simulation-{case_id}')
            brain = create_brain(io, f'edge-simulation-{case_id}', state_path=directory / 'state' / case_id / 'resume.json')
            current = None
            with running(brain) as brain_url:
                def turn(text='', action='answer', note=''):
                    nonlocal current
                    body = {'request_id': uuid.uuid4().hex, 'action': action, 'text': text}
                    if current and action == 'answer':
                        body.update({key: current[key] for key in ('session_id', 'question_id')})
                    current = checked(client.post(brain_url + '/voice/turn', headers=edge, json=body), f'Turn {action}')
                    transcript.append({'action': action, 'student': text, 'note': note,
                                       'robot': current['segments'], 'phase': current['phase'],
                                       'dialog_count': current['dialog_count'], 'result': current})
                    save()
                    return current

                turn(action='start')
                turn(scene['opening'], note='Student says the generated opening')
                limit = {'basic': 6, 'standard': 8, 'challenge': 10}[case['difficulty']]
                for index in range(limit):
                    if current['phase'] == 'done':
                        break
                    if case_id == 'g3_lunch' and index == 1:
                        before = current['dialog_count']
                        turn(action='howtosay', note='Student asks how to express an intention')
                        utterance = bridge.learner(case, scene, transcript, 'Give ONE simple Chinese intention relevant to the last in-character question. This is the how-do-I-say help input, not a normal English answer.')
                        turn(utterance['text'], note=utterance.get('note', ''))
                        phrase = brain.state.tutor.help_phrase
                        assert phrase
                        turn(phrase, note='Exact imitation of the help phrase; must not advance the conversation or claim independent speech')
                        assert current['dialog_count'] == before
                        turn(phrase, note='Student uses the modelled phrase in context with help still recorded')
                        continue
                    if case_id == 'g6_space_puzzle' and index == 1:
                        before = current['dialog_count']
                        turn(action='explain', note='Explain this question with Chinese help disabled')
                        assert current['dialog_count'] == before
                    extra = ''
                    if case_id == 'g3_lunch' and index == 0:
                        extra = 'Use a natural one- or two-word answer if the current question permits it.'
                    elif case_id == 'g3_lunch' and index == 2:
                        extra = 'Ask one relevant price question instead of simply answering, unless its answer is already given.'
                    elif case_id == 'g5_lost_item' and index == 1:
                        extra = 'Use one plausible small grammar mistake while communicating relevant information. Keep fictional facts consistent.'
                    elif case_id == 'g6_space_puzzle' and index == 2:
                        extra = 'Ask an unexpected but relevant clarification about the water tank clue; do not derail the mission.'
                    elif case_id == 'g4_student_shopkeeper':
                        extra = 'The ORIGINAL student design is that YOU are the shopkeeper and ask the questions. Keep that intention even if the generated card reverses your role; do not silently switch to customer. Welcome, ask what/how many, price, bag, payment, farewell as appropriate to the actual dialogue.'
                    utterance = bridge.learner(case, scene, transcript, f'Simulate a grade {case["grade"]} learner. Respond naturally to the actual last robot turn; pursue the original scene goal without pretending already-unfinished steps are completed. This is conversational turn {index + 1} of at most {limit}. {extra}')
                    turn(utterance['text'], note=utterance.get('note', ''))
                assert current['phase'] == 'done' and current['active'] is False, current
                evidence['progress'] = checked(client.get(public_url + '/api/progress', headers=parent, params=query), 'Read saved progress')
                evidence['model_status'] = checked(client.get(public_url + '/api/llm', headers=parent, params=query), 'Read own-model status')
                evidence['passed'] = True
                evidence['final_dialog_count'] = current['dialog_count']
                save()
                print('DONE', case_id, current['dialog_count'], flush=True)
    except Exception as exc:
        evidence['passed'] = False
        evidence['error'] = f'{type(exc).__name__}: {exc}'
        save()
        print('FAILED', case_id, evidence['error'], flush=True)
    return {'case_id': case_id, 'passed': evidence.get('passed', False), 'error': evidence.get('error', '')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--cases', required=True, type=Path)
    parser.add_argument('--only', nargs='*')
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding='utf-8'))
    if args.only:
        cases = [case for case in cases if case['id'] in args.only]
    assert cases
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    assert not (directory / 'simulation.sqlite3').exists(), 'Use a new directory to preserve the original evidence'
    bridge = ActorBridge(directory)
    store = Store(directory / 'simulation.sqlite3', Dictionary(ROOT / 'data/dictionary.json'))
    for case in cases:
        case_id = case['id']
        store.add_student(case_id, f'parent-simulation-{case_id}', f'brain-simulation-{case_id}')
    # A file-mediated human/GPT orchestration has no meaningful service latency.
    # This override is test-only; production keeps its 20-second deadline.
    public_api.SCENE_GENERATION_SECONDS = 600
    write_json(directory / 'run-metadata.json', {
        'mode': 'manual GPT actor; not external API', 'cases': cases,
        'test_only_override': {'scene_generation_seconds': 600},
        'production_timeout_seconds': 20,
        'other_limits': 'Actual PublicClient 90-second network timeout and actual dialogue turn limits retained',
    })
    with running(public_api.create_app(store, GPTActorProviders(bridge))) as public_url:
        with ThreadPoolExecutor(max_workers=len(cases)) as executor:
            futures = [executor.submit(run_case, case, public_url, bridge, directory) for case in cases]
            results = [future.result() for future in as_completed(futures)]
    write_json(directory / 'summary.json', results)
    print(json.dumps(results, ensure_ascii=False), flush=True)
    return 0 if all(result['passed'] for result in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
