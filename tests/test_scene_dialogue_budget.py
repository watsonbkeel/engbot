"""The real Tutor must tell the language model its actual finite turn budget.

These tests verify orchestration, not the semantic quality of generated speech.
Live GPT examples and the independent teaching review are separate evidence.
"""
import json

import pytest

from english_class.engine import Tutor
from test_v3_learning import SCENE, V3IO, enter


def dialogue_data(io):
    calls = [call for call in io.chat_calls
             if 'speaking partner' in call[0]['content'] or 'SCENE_DIALOGUE' in call[0]['content']]
    return json.loads(calls[-1][-1]['content'])


@pytest.mark.asyncio
@pytest.mark.parametrize('difficulty,limit', [('basic', 6), ('standard', 8), ('challenge', 10)])
async def test_scene_model_can_plan_against_the_actual_remaining_turns(difficulty, limit):
    io = V3IO(mode='scene', scene=SCENE, count=1)
    io.config_value['difficulty'] = difficulty
    tutor = Tutor(io)
    await tutor.turn(action='start', request_id='budget-scene-start')
    await tutor.turn(SCENE['opening'], request_id='budget-scene-opening')
    initial = dialogue_data(io)
    assert initial['dialogue_budget'] == {'total_turns': limit, 'completed_turns': 0, 'remaining_turns': limit}
    assert initial['closing'] is False
    for completed in range(1, limit + 1):
        result = await tutor.turn('An apple, please.', request_id=f'budget-scene-answer-{completed}')
        payload = dialogue_data(io)
        assert payload['dialogue_budget'] == {
            'total_turns': limit, 'completed_turns': completed, 'remaining_turns': limit - completed,
        }
        assert payload['closing'] is (completed == limit)
        assert result['dialog_count'] == completed
        assert result['active'] is (completed < limit)
    assert result['phase'] == 'done'


@pytest.mark.asyncio
@pytest.mark.parametrize('difficulty,limit', [('basic', 4), ('standard', 6), ('challenge', 8)])
async def test_generic_dialogue_uses_its_own_shorter_budget(difficulty, limit):
    io = V3IO(count=1)
    io.config_value['difficulty'] = difficulty
    tutor = Tutor(io)
    await enter(tutor, 'dialog')
    assert dialogue_data(io)['dialogue_budget'] == {'total_turns': limit, 'completed_turns': 0, 'remaining_turns': limit}
    for completed in range(1, limit + 1):
        result = await tutor.turn('An apple, please.', request_id=f'budget-generic-answer-{completed}')
    payload = dialogue_data(io)
    assert payload['dialogue_budget'] == {'total_turns': limit, 'completed_turns': limit, 'remaining_turns': 0}
    assert payload['closing'] is True and result['phase'] == 'done'


@pytest.mark.asyncio
async def test_help_imitation_unclear_and_repeat_do_not_spend_a_dialogue_turn():
    io = V3IO(mode='scene', scene=SCENE, count=1)
    tutor = Tutor(io)
    await tutor.turn(action='start', request_id='budget-help-start')
    await tutor.turn(SCENE['opening'], request_id='budget-help-opening')
    for action in ('repeat', 'explain', 'howtosay'):
        await tutor.turn(action=action, request_id='budget-help-' + action)
        assert tutor.dialog_count == 0
    await tutor.turn('我想买一个苹果', request_id='budget-help-intent')
    await tutor.turn('I would like an apple.', request_id='budget-help-imitation')
    await tutor.turn('', unclear=True, request_id='budget-help-unclear')
    assert tutor.dialog_count == 0
    await tutor.turn('I would like an apple.', request_id='budget-help-actual-answer')
    payload = dialogue_data(io)
    assert payload['dialogue_budget'] == {'total_turns': 6, 'completed_turns': 1, 'remaining_turns': 5}
    assert payload['answer_support']['help_requested'] is True
    assert io.rows['a']['status'] == 0
