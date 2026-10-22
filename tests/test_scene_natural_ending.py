"""Scene completion ends a role-play, not a vocabulary assessment.

The optional model signal is validated by real Tutor code; model semantics are
reviewed separately in the recorded GPT scene examples.
"""
import json

import pytest

from english_class.client import ServiceError
from english_class.engine import Tutor
from test_v3_learning import SCENE, V3IO, enter, say


class EndingIO(V3IO):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.completion_signal = False
        self.relevance_override = None

    async def chat(self, messages, json_output=True):
        content = await super().chat(messages, json_output)
        if 'SCENE_DIALOGUE' in messages[0]['content'] or 'speaking partner' in messages[0]['content']:
            obj = json.loads(content)
            obj['scene_complete'] = self.completion_signal
            if self.relevance_override is not None:
                obj['relevant'] = self.relevance_override
            return json.dumps(obj)
        return content


async def start_scene(io):
    tutor = Tutor(io)
    await tutor.turn(action='start', request_id='ending-start')
    await tutor.turn(SCENE['opening'], request_id='ending-opening')
    return tutor


@pytest.mark.asyncio
async def test_completed_scene_keeps_farewell_and_review_without_filler_turns():
    io = EndingIO(mode='scene', scene=SCENE, count=1)
    tutor = await start_scene(io)
    await tutor.turn('How much is it?', request_id='ending-price')
    io.completion_signal = True
    io.dialog_reply = 'Here is your bag. Goodbye!'
    result = await tutor.turn('Thank you. Goodbye!', request_id='ending-farewell')
    assert result['phase'] == 'done' and result['active'] is False
    assert result['dialog_count'] == 2
    assert 'Here is your bag. Goodbye!' in say(result)
    assert len([call for call in io.chat_calls if 'SCENE_REVIEW' in call[0]['content']]) == 1
    assert io.writes == []  # Scene completion is not target-word evidence.
    assert io.rows == {}


@pytest.mark.asyncio
async def test_model_cannot_finish_at_opening_or_before_two_learner_turns():
    io = EndingIO(mode='scene', scene=SCENE, count=1)
    io.completion_signal = True
    tutor = await start_scene(io)
    assert tutor.phase == 'dialog' and tutor.dialog_count == 0
    result = await tutor.turn('How much is it?', request_id='ending-first-answer')
    assert result['active'] is True and result['dialog_count'] == 1
    assert not any('SCENE_REVIEW' in call[0]['content'] for call in io.chat_calls)


@pytest.mark.asyncio
async def test_generic_dialogue_does_not_treat_scene_signal_as_a_stop():
    io = EndingIO(count=1)
    io.completion_signal = True
    tutor = Tutor(io)
    await enter(tutor, 'dialog')
    for index in range(2):
        result = await tutor.turn('Hello there.', request_id=f'ending-generic-{index}')
    assert result['phase'] == 'dialog' and result['active'] is True


@pytest.mark.asyncio
async def test_contradictory_irrelevant_answer_cannot_trigger_natural_completion():
    io = EndingIO(mode='scene', scene=SCENE, count=1)
    tutor = await start_scene(io)
    await tutor.turn('How much is it?', request_id='ending-relevant-first')
    io.completion_signal = True
    io.relevance_override = False
    result = await tutor.turn('My spaceship is purple.', request_id='ending-irrelevant-last')
    assert result['phase'] == 'dialog' and result['active'] is True
    assert result['dialog_count'] == 2
    assert not any('SCENE_REVIEW' in call[0]['content'] for call in io.chat_calls)


@pytest.mark.asyncio
@pytest.mark.parametrize('malformed', ['true', 1, None, []])
async def test_malformed_completion_signal_does_not_advance_or_write(malformed):
    io = EndingIO(mode='scene', scene=SCENE, count=1)
    tutor = await start_scene(io)
    before = (tutor.dialog_count, len(tutor.history), len(io.writes))
    io.completion_signal = malformed
    with pytest.raises(ServiceError, match='AI对话格式'):
        await tutor.turn('An apple, please.', request_id='ending-invalid-signal')
    assert (tutor.dialog_count, len(tutor.history), len(io.writes)) == before
    io.completion_signal = False
    result = await tutor.turn('An apple, please.', request_id='ending-valid-retry')
    assert result['active'] is True and result['dialog_count'] == 1


@pytest.mark.asyncio
async def test_old_model_without_completion_field_keeps_the_existing_hard_cap():
    io = V3IO(mode='scene', scene=SCENE, count=1)
    tutor = await start_scene(io)
    for index in range(6):
        result = await tutor.turn('Hello there.', request_id=f'ending-old-provider-{index}')
        assert result['active'] is (index < 5)
    assert result['phase'] == 'done' and result['dialog_count'] == 6


@pytest.mark.asyncio
async def test_new_scene_and_old_snapshot_do_not_reuse_previous_completion():
    io = EndingIO(mode='scene', scene=SCENE, count=1)
    tutor = await start_scene(io)
    await tutor.turn('Hello there.', request_id='ending-before-first')
    io.completion_signal = True
    await tutor.turn('Thank you. Goodbye!', request_id='ending-before-last')
    io.completion_signal = False
    await tutor.turn(action='start', request_id='ending-restart')
    await tutor.turn(SCENE['opening'], request_id='ending-restart-opening')
    old = tutor.export_state()
    old['state'].pop('_scene_complete', None)
    tutor.restore_state(old)
    for index in range(2):
        result = await tutor.turn('Hello there.', request_id=f'ending-after-restart-{index}')
    assert result['phase'] == 'dialog' and result['dialog_count'] == 2
