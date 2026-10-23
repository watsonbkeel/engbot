"""Small, shared API contracts. Extra fields are rejected to catch classroom bugs."""
from __future__ import annotations
from typing import Literal
from datetime import datetime
import re
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator, field_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')

class SceneConfig(StrictModel):
    name: str = Field(min_length=1, max_length=40)
    robot_role: str = Field(min_length=1, max_length=40)
    student_role: str = Field(min_length=1, max_length=40)
    goal: str = Field(min_length=1, max_length=200)
    opening: str = Field(min_length=1, max_length=60)

    @field_validator('name','robot_role','student_role','goal','opening',mode='before')
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value,str) else value

    @field_validator('opening')
    @classmethod
    def english_opening(cls,value):
        if not re.search(r'[A-Za-z]',value) or re.search(r"[^A-Za-z0-9\s.,!?;:'\"’\-]",value):
            raise ValueError('开场白须为英文短句')
        return value

class SceneDraftInput(StrictModel):
    description: str = Field(min_length=5,max_length=200)
    grade: StrictInt = Field(default=1,ge=1,le=12)

    @field_validator('description',mode='before')
    @classmethod
    def trim(cls,value): return value.strip() if isinstance(value,str) else value

class HeartbeatInput(StrictModel):
    pi: StrictBool = False

class LearningConfig(StrictModel):
    grade: StrictInt = Field(default=1, ge=1, le=12)
    semester: StrictInt = Field(default=1, ge=1, le=2)
    unit: StrictInt = Field(default=0, ge=0, le=2000)
    duration_minutes: Literal[5, 10, 15, 20, 30] = 10
    practice_words: StrictInt = Field(default=3, ge=1, le=10)
    chinese_help: StrictBool = True
    difficulty: Literal['basic', 'standard', 'challenge'] = 'basic'
    mode: Literal['full','en2zh','zh2en','scene'] = 'full'
    scene: SceneConfig | None = None

class LlmSettings(StrictModel):
    base_url: str = Field(min_length=8, max_length=300)
    model: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9._:/@+-]+$')
    api_key: str | None = Field(default=None, max_length=400)
    thinking: StrictBool = False
    allow_platform_fallback: StrictBool = False

class Evidence(StrictModel):
    """一次练习的附加证据；可选，旧客户端不传也可以。"""
    answer_valid: StrictBool = False
    used_word: StrictBool = False
    imitated: StrictBool = False

class ProgressUpdate(StrictModel):
    word_id: str = Field(min_length=1, max_length=128)
    status: StrictInt | None = Field(default=None, ge=0, le=2)
    unclear: StrictBool = False
    evidence: Evidence | None = None

    @model_validator(mode='after')
    def check_unclear(self):
        if self.unclear and self.status is not None:
            raise ValueError('没听清时 status 必须为 null，不得改变学习状态')
        if self.unclear and self.evidence and any(self.evidence.model_dump().values()):
            raise ValueError('没听清时不得记录回答证据')
        return self

class ChatMessage(StrictModel):
    role: Literal['system', 'user', 'assistant']
    content: str = Field(max_length=24000)

class ChatInput(StrictModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)
    json_output: bool = False

class Segment(StrictModel):
    text: str = Field(min_length=1, max_length=1000)
    language: Literal['zh', 'en'] = 'en'

class SpeechInput(StrictModel):
    segments: list[Segment] = Field(min_length=1, max_length=8)
    slow: bool = False
    speed: Literal['elementary','middle','high'] = 'middle'

class ChatTurnInput(StrictModel):
    action: Literal['enter','answer','stop'] = 'answer'
    text: str = Field(default='', max_length=1000)
    request_id: str = Field(min_length=8, max_length=128)
    session_id: str = Field(min_length=8, max_length=64)


class LessonRecordInput(StrictModel):
    session_id: str = Field(min_length=8, max_length=64)
    revision: StrictInt = Field(ge=1)
    mode: Literal['full', 'en2zh', 'zh2en', 'scene']
    scene_name: str = Field(default='', max_length=40)
    started_at: datetime
    ended_at: datetime | None = None
    elapsed_seconds: StrictInt = Field(ge=0, le=86400)
    dialog_count: StrictInt = Field(ge=0, le=10000)
    status: Literal['in_progress', 'completed', 'stopped']
    review_status: Literal['pending', 'success', 'failed', 'not_applicable']
    review_segments: list[Segment] = Field(default_factory=list, max_length=4)
    review_error: Literal['', 'ReviewProviderFailed', 'ReviewPromptInvalid', 'ReviewJsonInvalid', 'ReviewPraiseInvalid', 'ReviewTipsInvalid', 'ReviewLanguageInvalid'] = ''

    @field_validator('started_at', 'ended_at')
    @classmethod
    def aware_datetime(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError('时间必须包含时区')
        return value

    @model_validator(mode='after')
    def validate_lesson(self):
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError('结束时间不能早于开始时间')
        if self.status == 'in_progress' and self.ended_at is not None:
            raise ValueError('进行中的课堂不能有结束时间')
        if self.status != 'in_progress' and self.ended_at is None:
            raise ValueError('已结束课堂必须有结束时间')
        if self.review_status == 'success' and not self.review_segments:
            raise ValueError('review成功必须包含segments')
        if self.review_status != 'success' and self.review_segments:
            raise ValueError('非review成功不得包含segments')
        if self.review_status == 'failed' and not self.review_error:
            raise ValueError('review失败必须包含error')
        if self.review_status != 'failed' and self.review_error:
            raise ValueError('非review失败不得包含error')
        return self


class TurnInput(StrictModel):
    text: str = Field(default='', max_length=2000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    unclear: bool = False
    request_id: str = Field(min_length=8, max_length=128)
    action: Literal['answer', 'start', 'stop', 'pause', 'resume', 'repeat', 'slow', 'help', 'explain', 'howtosay', 'tick', 'played'] = 'answer'
    session_id: str | None = Field(default=None,max_length=64)
    question_id: str | None = Field(default=None,max_length=64)

    @model_validator(mode='after')
    def paired_identity(self):
        if (self.session_id is None)!=(self.question_id is None):
            raise ValueError('session_id 和 question_id 必须同时传入')
        return self
