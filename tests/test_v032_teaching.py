"""Teaching regressions: real Tutor, deterministic model fixtures only under tests/."""
import copy
import json

import pytest

from english_class.engine import Tutor
from test_v3_learning import SCENE, V3IO, enter, say


class TeachingIO(V3IO):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.vocabulary_correct = None

    async def chat(self, messages, json_output=True):
        if 'VOCABULARY_JUDGE' in messages[0]['content'] and self.vocabulary_correct is not None:
            self.chat_calls.append(copy.deepcopy(messages))
            return json.dumps({'correct': self.vocabulary_correct})
        return await super().chat(messages, json_output)


def last_call(io, marker):
    return next(call for call in reversed(io.chat_calls) if marker in call[0]['content'])


def test_everyday_templates_precede_and_preserve_original_interest_scenes():
    from english_class.scene_prompts import scene_templates
    templates = scene_templates()['templates']
    assert [row['key'] for row in templates[:2]] == ['stationery', 'lunch']
    assert {'jungle', 'normandy', 'nuclear'} <= {row['key'] for row in templates}
    for scene in templates[:2]:
        assert 2 <= len(scene['opening'].split()) <= 6


@pytest.mark.asyncio
@pytest.mark.parametrize('answer', ['apple banana orange', 'I cannot say apple', 'banana or apple'])
async def test_word_repetition_does_not_pass_a_list_or_unrelated_mention(answer):
    io = TeachingIO(mode='zh2en', count=1)
    tutor = Tutor(io)
    await tutor.turn(action='start', request_id='repeat-start')
    await tutor.turn('orange', request_id='repeat-wrong-recall')
    writes = len(io.writes)
    result = await tutor.turn(answer, request_id='repeat-first-try')
    assert tutor.phase == 'repeat' and len(io.writes) == writes
    assert '这次跟读说出来了' not in say(result)
    result = await tutor.turn(answer, request_id='repeat-second-try')
    assert result['phase'] == 'done'
    assert io.evidence[-1][2] == {'answer_valid': False, 'used_word': False, 'imitated': False}


@pytest.mark.asyncio
@pytest.mark.parametrize('answer', ['appled', 'appling'])
async def test_word_repetition_rejects_invented_inflections(answer):
    io = TeachingIO(mode='zh2en', count=1)
    tutor = Tutor(io)
    await tutor.turn(action='start', request_id='invented-start')
    await tutor.turn('orange', request_id='invented-wrong-recall')
    writes = len(io.writes)
    result = await tutor.turn(answer, request_id='invented-first-try')
    assert tutor.phase == 'repeat' and len(io.writes) == writes
    assert '这次跟读说出来了' not in say(result)
    result = await tutor.turn(answer, request_id='invented-second-try')
    assert result['phase'] == 'done'
    assert io.evidence[-1][2] == {'answer_valid': False, 'used_word': False, 'imitated': False}


@pytest.mark.asyncio
async def test_word_repetition_requires_the_demonstrated_form():
    io = TeachingIO(mode='zh2en', count=1)
    tutor = Tutor(io)
    await tutor.turn(action='start', request_id='form-start')
    await tutor.turn('orange', request_id='form-wrong-recall')
    writes = len(io.writes)
    await tutor.turn('apples', request_id='form-different-number')
    assert tutor.phase == 'repeat' and len(io.writes) == writes
    await tutor.turn('apple', request_id='form-demonstrated')
    assert io.evidence[-1][2]['imitated'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(('word', 'answer'), [('apple', 'APPLE!'), ('apple', '  apple.  '),
                                            ('apples', 'APPLES!'), ('get up', 'GET UP!')])
async def test_word_repetition_keeps_case_punctuation_and_spacing_tolerance(word, answer):
    io = TeachingIO(mode='zh2en', count=1)
    io.words_value[0]['word'] = word
    tutor = Tutor(io)
    await tutor.turn(action='start', request_id='repeat-start')
    await tutor.turn('orange', request_id='repeat-wrong-recall')
    await tutor.turn(answer, request_id='repeat-accepted')
    assert io.evidence[-1][2] == {'answer_valid': False, 'used_word': False, 'imitated': True}
    assert io.rows['a']['status'] == 0


@pytest.mark.asyncio
async def test_wrong_dialogue_use_after_a_model_is_not_successful_imitation():
    io = TeachingIO(mode='scene', scene=SCENE, count=1)
    tutor = Tutor(io)
    await tutor.turn(action='start', request_id='dialog-start')
    await tutor.turn('Hi sir', request_id='dialog-opening')
    tutor.result([{'text': 'You can say: I want an apple. What would you like?', 'language': 'en'}])
    io.word_evidence = [{'word_id': 'a', 'correct': False, 'independent': False}]
    await tutor.turn('apple is a car', request_id='dialog-wrong-copy')
    assert io.evidence[-1][2] == {'answer_valid': False, 'used_word': False, 'imitated': False}
    assert io.rows['a']['status'] == 0


@pytest.mark.asyncio
async def test_wrong_recall_mention_after_help_is_not_successful_imitation():
    io = TeachingIO(mode='zh2en', count=1)
    tutor = Tutor(io)
    await tutor.turn(action='start', request_id='recall-start')
    await tutor.turn(action='explain', request_id='recall-help')
    await tutor.turn('apple banana orange', request_id='recall-guesses')
    assert tutor.phase == 'repeat'
    assert io.evidence[-1][2]['imitated'] is False
    assert io.rows['a']['status'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('chinese_help', [True, False])
async def test_correct_paraphrase_feedback_does_not_claim_target_retrieval(chinese_help):
    io = TeachingIO(count=1)
    io.config_value['chinese_help'] = chinese_help
    tutor = Tutor(io)
    await enter(tutor, 'recall')
    io.vocabulary_correct = True
    result = await tutor.turn('a red fruit', request_id='recall-paraphrase')
    assert '对！' not in say(result) and 'Right!' not in say(result)
    assert io.evidence[-1] == ('a', None, {'answer_valid': True, 'used_word': False, 'imitated': False})
    assert io.rows['a']['status'] == 1


@pytest.mark.asyncio
async def test_dialogue_and_review_receive_support_for_the_actual_learner_line():
    io = TeachingIO(mode='scene', scene=SCENE, count=1)
    tutor = Tutor(io)
    await tutor.turn(action='start', request_id='support-start')
    await tutor.turn('Hi sir', request_id='support-opening')
    await tutor.turn(action='howtosay', request_id='support-help')
    await tutor.turn('我想买一个苹果', request_id='support-intent')
    await tutor.turn('I would like an apple.', request_id='support-echo')
    await tutor.turn('I would like an apple.', request_id='support-answer')
    data = json.loads(last_call(io, 'SCENE_DIALOGUE')[-1]['content'])
    support = data['answer_support']
    assert support['help_requested'] is True and support['modelled_word_ids'] == ['a']
    assert support['assisted_word_ids'] == ['a']
    await tutor.turn('I want a banana', request_id='support-next-answer')
    data = json.loads(last_call(io, 'SCENE_DIALOGUE')[-1]['content'])
    assert data['answer_support']['help_requested'] is False
    await tutor.turn(action='stop', request_id='support-stop')
    review = json.loads(last_call(io, 'SCENE_REVIEW')[-1]['content'])
    learner_lines = [line for line in review['history'] if line['role'] == 'user']
    assert learner_lines[0]['support'] == support
    assert learner_lines[1]['support']['help_requested'] is False
    assert io.rows['a']['status'] == 0


@pytest.mark.asyncio
async def test_help_support_is_preserved_when_scene_has_no_target_words():
    io = TeachingIO(mode='scene', scene=SCENE, count=1)
    io.words_value = []
    tutor = Tutor(io)
    await tutor.turn(action='start', request_id='empty-start')
    await tutor.turn('Hi sir', request_id='empty-opening')
    await tutor.turn(action='explain', request_id='empty-help')
    await tutor.turn('An apple, please', request_id='empty-answer')
    data = json.loads(last_call(io, 'SCENE_DIALOGUE')[-1]['content'])
    assert data['answer_support']['help_requested'] is True
    assert io.writes == []


@pytest.mark.asyncio
async def test_current_word_difficulty_reaches_dialogue_despite_historical_high_status():
    io = TeachingIO(count=1)
    io.rows['a'] = {'word_id': 'a', 'status': 2, 'unclear_count': 0}
    tutor = Tutor(io)
    await enter(tutor, 'recall')
    await tutor.turn('orange', request_id='observation-wrong')
    await tutor.turn('apple', request_id='observation-repeat')
    data = json.loads(last_call(io, 'speaking partner')[-1]['content'])
    observed = {row['word_id']: row for row in data['session_word_observations']}
    assert observed['a'] == {'word_id': 'a', 'phase': 'repeat', 'correct': True,
                             'independent': False, 'imitated': True}
    assert io.rows['a']['status'] == 2
    assert 'historical_status' not in observed['a']


@pytest.mark.asyncio
async def test_unclear_recognition_does_not_create_a_negative_learning_observation():
    io = TeachingIO(mode='scene', scene=SCENE, count=1)
    tutor = Tutor(io)
    await tutor.turn(action='start', request_id='unclear-start')
    await tutor.turn('Hi sir', request_id='unclear-opening')
    await tutor.turn('apple', unclear=True, request_id='unclear-response')
    await tutor.turn('I want an apple', request_id='clear-response')
    data = json.loads(last_call(io, 'SCENE_DIALOGUE')[-1]['content'])
    assert data['session_word_observations'] == []


@pytest.mark.asyncio
async def test_new_session_clears_last_session_learning_observations():
    io = TeachingIO(mode='zh2en', count=1)
    tutor = Tutor(io)
    await tutor.turn(action='start', request_id='new-start')
    await tutor.turn('orange', request_id='new-wrong')
    await tutor.turn('apple', request_id='new-repeat')
    io.config_value.update(mode='scene', scene=SCENE)
    await tutor.turn(action='start', request_id='new-session')
    await tutor.turn('Hi sir', request_id='new-opening')
    data = json.loads(last_call(io, 'SCENE_DIALOGUE')[-1]['content'])
    assert data['session_word_observations'] == []


@pytest.mark.asyncio
async def test_v031_snapshot_gets_new_defaults_without_retaining_failed_turn_state():
    io = TeachingIO(mode='scene', scene=SCENE, count=1)
    tutor = Tutor(io)
    await tutor.turn(action='start', request_id='legacy-start')
    await tutor.turn('Hi sir', request_id='legacy-opening')
    snapshot = json.loads(json.dumps(tutor.export_state()))
    snapshot['state'].pop('lesson_observations', None)
    snapshot['state'].pop('task_helped', None)
    tutor.lesson_observations = {'a': {'word_id': 'a', 'correct': False}}
    tutor.task_helped = True
    tutor._failed_turn_only = 'must disappear'
    tutor.restore_state(snapshot)
    assert tutor.lesson_observations == {} and tutor.task_helped is False
    assert not hasattr(tutor, '_failed_turn_only')
    await tutor.turn('I want an apple', request_id='legacy-answer')
    assert io.rows['a']['status'] == 2


@pytest.mark.asyncio
async def test_resume_carries_current_observations_without_changing_original_word_ids(tmp_path):
    io = TeachingIO(count=2)
    path = tmp_path / 'resume.json'
    tutor = Tutor(io, state_path=path)
    await enter(tutor, 'recall')
    await tutor.turn('orange', request_id='resume-wrong')
    await tutor.turn('apple', request_id='resume-repeat')
    await tutor.turn(action='stop', request_id='resume-stop')
    restored = Tutor(io, state_path=path)
    await restored.turn(action='start', request_id='resume-start')
    await restored.turn('banana', request_id='resume-second-word')
    data = json.loads(last_call(io, 'speaking partner')[-1]['content'])
    observations = {row['word_id']: row for row in data['session_word_observations']}
    assert observations['a']['imitated'] is True and observations['a']['independent'] is False
    assert observations['b']['independent'] is True
    assert set(observations) == {'a', 'b'}
