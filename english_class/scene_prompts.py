"""Read the audited, server-owned prompt blocks. Parent text is always data."""
from __future__ import annotations
import json
import re
from pathlib import Path
from .models import SceneConfig

DEFAULT_PATH=Path(__file__).resolve().parents[1]/'prompts/scenes.md'

def read_blocks(path=None) -> dict[str,str]:
    text=Path(path or DEFAULT_PATH).read_text(encoding='utf-8')
    blocks={}
    for match in re.finditer(r'^```(?:text|json)\s+id=([a-z_]+)\s*\n(.*?)^```\s*$',text,re.M|re.S):
        if match[1] in blocks: raise ValueError('重复的场景提示词段落')
        blocks[match[1]]=match[2].strip()
    return blocks

def render_prompt(name:str, **values) -> str:
    blocks=read_blocks()
    if name not in blocks: raise ValueError(f'缺少场景提示词：{name}')
    try: return blocks[name].format_map(values)
    except (KeyError,ValueError) as exc: raise ValueError(f'场景提示词参数不完整：{name}') from exc

def scene_templates() -> dict:
    blocks=read_blocks()
    templates=json.loads(blocks['templates']); examples=json.loads(blocks['examples'])
    if not isinstance(templates,list) or not isinstance(examples,list) or not all(isinstance(x,str) for x in examples):
        raise ValueError('场景模板或示例格式错误')
    checked=[]
    for template in templates:
        scene=SceneConfig.model_validate({k:v for k,v in template.items() if k!='key'})
        checked.append({'key':str(template.get('key',scene.name)),**scene.model_dump()})
    return {'templates':checked,'examples':examples,
            'copy_for_parent':render_prompt('scene_copy_for_parent',grade='当前',description='（请填写场景想法）')}

def grade_hint(grade:int) -> str:
    if grade<=3: return '1-3 (early primary, very simple words)'
    if grade<=6: return '4-6 (upper primary)'
    if grade<=9: return '7-9 (junior high)'
    return '10-12 (senior high)'
