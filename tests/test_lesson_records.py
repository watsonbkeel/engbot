from datetime import datetime, timezone

import pytest

from english_class.models import LessonRecordInput
from english_class.store import Conflict


def headers(role='brain', student='A'):
    return {'Authorization': f'Bearer {role.title()}_{student}_very_long_token'}


def payload(**changes):
    value = {
        'session_id': 'session-1234', 'revision': 1, 'mode': 'full', 'scene_name': '',
        'started_at': datetime(2026, 1, 1, 1, tzinfo=timezone.utc), 'ended_at': None,
        'elapsed_seconds': 0, 'dialog_count': 0, 'status': 'in_progress',
        'review_status': 'pending', 'review_segments': [], 'review_error': '',
    }
    value.update(changes)
    return value


def test_lesson_input_requires_aware_time_and_consistent_close():
    with pytest.raises(ValueError):
        LessonRecordInput.model_validate(payload(started_at=datetime(2026, 1, 1)))
    with pytest.raises(ValueError):
        LessonRecordInput.model_validate(payload(status='completed'))


def test_review_consistency():
    with pytest.raises(ValueError):
        LessonRecordInput.model_validate(payload(review_status='success'))
    with pytest.raises(ValueError):
        LessonRecordInput.model_validate(payload(review_status='failed'))


def test_store_revision_conflict_and_immutable_fields(db):
    db.add_student('s001', 'Parent_A_very_long_token', 'Brain_A_very_long_token')
    first = db.record_lesson('s001', payload())
    assert first['revision'] == 1
    assert db.record_lesson('s001', payload())['revision'] == 1
    with pytest.raises(Conflict):
        db.record_lesson('s001', payload(scene_name='changed', revision=2))
    with pytest.raises(Conflict):
        db.record_lesson('s001', payload(revision=1, dialog_count=1))


def test_lesson_authentication_roles(client):
    body = payload()
    assert client.post('/api/lessons?student_id=s001', headers=headers('parent'), json=body).status_code == 403
    assert client.post('/api/lessons?student_id=s001', headers=headers('brain'), json=body).status_code == 200
    assert client.get('/api/lessons?student_id=s001', headers=headers('parent')).status_code == 200
