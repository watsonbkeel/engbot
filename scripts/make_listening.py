#!/usr/bin/env python3
"""Build real listening MP3s from curated originals, or verify delivered assets offline.

No model/provider fallback is simulated. Generation failures are recorded explicitly.
Existing valid assets with the same full transcript are resumed regardless of engine;
use --force to intentionally regenerate selected assets with a different voice.
"""
from __future__ import annotations
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import wave

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = ROOT / 'data/listening'
MIN_SECONDS, MAX_SECONDS = 60.0, 180.0
IDENTIFIER = re.compile(r'^[A-Za-z0-9_-]+$')


class BuildError(ValueError):
    """Safe messages with stable codes, without provider URLs or credentials."""

    def __init__(self, message: str, *, code: str = 'BUILD_ERROR'):
        super().__init__(message)
        self.code = code


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f'无法读取 JSON：{path.name}（{type(exc).__name__}）') from exc
    if not isinstance(data, dict):
        raise BuildError(f'{path.name} 须为 JSON 对象')
    return data


def load_curated(path: Path) -> list[dict]:
    rows = read_json(path).get('items')
    if not isinstance(rows, list) or not rows:
        raise BuildError('curated.json 缺少 items')
    ids, counts = set(), Counter()
    for row in rows:
        if not isinstance(row, dict): raise BuildError('每篇文稿必须为对象')
        identifier, grade, kind = row.get('id'), row.get('grade'), row.get('type')
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier) or identifier in ids:
            raise BuildError('素材 id 非法或重复')
        if type(grade) is not int or not 1 <= grade <= 9 or kind not in ('story', 'dialogue'):
            raise BuildError(f'{identifier} 年级或类型不合法')
        if row.get('file') != f'g{grade}/{identifier}.mp3':
            raise BuildError(f'{identifier} file 路径须为 g年级/id.mp3，不能越界', code='ASSET_PATH_INVALID')
        if not isinstance(row.get('title'), str) or not row['title'].strip():
            raise BuildError(f'{identifier} 缺少标题')
        if not isinstance(row.get('transcript'), str) or len(row['transcript'].split()) < 80:
            raise BuildError(f'{identifier} 缺少足够的完整英文文稿')
        ids.add(identifier); counts[(grade, kind)] += 1
    for grade in range(1, 10):
        if counts[(grade, 'story')] < 2 or counts[(grade, 'dialogue')] < 2 or sum(counts[(grade, x)] for x in ('story', 'dialogue')) < 5:
            raise BuildError(f'{grade} 年级须至少5篇，且短文/对话各至少2篇')
    return rows


def ensure_no_links(path: Path) -> None:
    current = path.absolute()
    for part in (current, *current.parents):
        if part.is_symlink(): raise BuildError('素材输出路径不能经过符号链接', code='PATH_SYMLINK')


def safe_asset(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not re.fullmatch(r'g[1-9]/[A-Za-z0-9_-]+\.mp3', relative):
        raise BuildError('音频 file 路径不合法', code='ASSET_PATH_INVALID')
    target = root / relative
    ensure_no_links(target)
    if root.resolve() not in target.resolve().parents: raise BuildError('音频路径越界', code='ASSET_OUTSIDE_ROOT')
    return target


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): result.update(block)
    return result.hexdigest()


def probe(path: Path, require_mp3: bool = True) -> float:
    try:
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=codec_name,codec_type', '-of', 'json', str(path)],
                                capture_output=True, text=True, timeout=30, check=True)
        data = json.loads(result.stdout)
        seconds = float(data['format']['duration'])
        streams = data.get('streams', [])
        if not math.isfinite(seconds) or seconds <= 0: raise ValueError()
        if not streams or not any(x.get('codec_type') == 'audio' for x in streams): raise ValueError()
        if require_mp3 and any(x.get('codec_name') != 'mp3' for x in streams): raise ValueError()
        return seconds
    except (OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError) as exc:
        raise BuildError(f'{path.name} 不是可读取的音频；请检查 ffprobe 安装与生成结果') from exc


def validate_asset(entry: dict, original: dict, root: Path) -> float:
    for key in ('id', 'grade', 'type', 'title', 'transcript', 'file'):
        if entry.get(key) != original.get(key): raise BuildError(f'{original["id"]} 清单与原稿字段不一致：{key}')
    target = safe_asset(root, entry['file'])
    if not target.is_file(): raise BuildError(f'{entry["id"]} 音频缺失', code='ASSET_MISSING')
    if entry.get('sha256') != digest(target): raise BuildError(f'{entry["id"]} 音频摘要不一致', code='ASSET_DIGEST_MISMATCH')
    seconds = probe(target)
    if not MIN_SECONDS <= seconds <= MAX_SECONDS: raise BuildError(f'{entry["id"]} 实测时长不在60–180秒')
    claimed = entry.get('duration_seconds')
    if not isinstance(claimed, (int, float)) or not math.isfinite(claimed) or abs(claimed - seconds) > 0.1:
        raise BuildError(f'{entry["id"]} 清单时长与 ffprobe 实测不符')
    synthesis = entry.get('synthesis', {})
    if not isinstance(synthesis, dict) or synthesis.get('engine') not in ('edge-tts', 'piper-tts'):
        raise BuildError(f'{entry["id"]} 缺少真实语音引擎生成记录')
    return seconds


def load_index(root: Path) -> dict[str, dict]:
    manifest = root / 'index.json'
    if not manifest.exists(): return {}
    entries = read_json(manifest).get('items')
    if not isinstance(entries, list): raise BuildError('index.json 缺少 items')
    out = {}
    for row in entries:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or row['id'] in out:
            raise BuildError('index.json 存在非法或重复 id')
        out[row['id']] = row
    return out


def verify(rows: list[dict], root: Path) -> dict:
    existing = load_index(root)
    expected = {row['id'] for row in rows}
    if set(existing) != expected: raise BuildError(f'清单须完整对应全部 {len(rows)} 篇原稿，不能缺项或多项')
    durations = [validate_asset(existing[row['id']], row, root) for row in rows]
    return {'verified': len(rows), 'min_seconds': round(min(durations), 3), 'max_seconds': round(max(durations), 3),
            'total_seconds': round(sum(durations), 3), 'bytes': sum(safe_asset(root, row['file']).stat().st_size for row in rows)}


def atomic_json(path: Path, value: dict) -> None:
    ensure_no_links(path)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.chmod(temporary, stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def spoken_text(row: dict) -> str:
    if row['type'] != 'dialogue': return row['transcript']
    return re.sub(r'(?m)^[A-Z][A-Za-z ]{0,18}:\s*', '', row['transcript'])


def target_wpm(grade: int) -> int:
    return 110 if grade <= 3 else 125 if grade <= 6 else 140


async def edge_speech(text: str, output: Path, voice: str) -> dict:
    import edge_tts
    await asyncio.wait_for(edge_tts.Communicate(text, voice=voice).save(str(output)), timeout=60)
    return {'engine': 'edge-tts', 'version': version('edge-tts'), 'voice': voice}


class PiperSpeech:
    def __init__(self, model: Path):
        if not model.is_file() or not Path(str(model) + '.json').is_file():
            raise BuildError('Piper 需要已下载的 .onnx 模型及同名 .onnx.json 配置', code='PIPER_MODEL_MISSING')
        import onnxruntime as ort
        from piper import PiperVoice
        from piper.config import PiperConfig
        from piper.voice import ESPEAK_DATA_DIR
        options = ort.SessionOptions(); options.intra_op_num_threads = 2; options.inter_op_num_threads = 1
        ort.disable_telemetry_events()
        self.voice = PiperVoice(config=PiperConfig.from_dict(read_json(Path(str(model) + '.json'))),
                                session=ort.InferenceSession(str(model), sess_options=options, providers=['CPUExecutionProvider']),
                                espeak_data_dir=ESPEAK_DATA_DIR)
        self.model_name = model.stem; self.model_sha256 = digest(model)

    def save(self, text: str, output: Path, grade: int) -> dict:
        from piper import SynthesisConfig
        scale = 1.30 if grade <= 3 else 1.18 if grade <= 6 else 1.05
        with wave.open(str(output), 'wb') as stream:
            self.voice.synthesize_wav(text, stream, SynthesisConfig(length_scale=scale, noise_scale=0.55, noise_w_scale=0.65))
        return {'engine': 'piper-tts', 'version': version('piper-tts'), 'voice': self.model_name,
                'model_sha256': self.model_sha256, 'length_scale': scale}


def encode(raw: Path, output: Path, row: dict) -> dict:
    seconds = probe(raw, require_mp3=False)
    # Change speech tempo only; do not insert silence, repeat speech, or pad a file.
    words = len(row['transcript'].split()); wpm = target_wpm(row['grade'])
    target = max(63.0, min(175.0, words / wpm * 60.0))
    tempo = seconds / target
    if not 0.5 <= tempo <= 2.0: raise BuildError(f'{row["id"]} 所需调速超出0.5–2.0倍，请调整文稿或语音参数')
    try:
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(raw), '-af', f'atempo={tempo:.6f}',
                        '-codec:a', 'libmp3lame', '-b:a', '64k', '-ar', '22050', '-ac', '1', str(output)],
                       capture_output=True, timeout=60, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise BuildError(f'{row["id"]} ffmpeg 编码失败；未发布此条音频') from exc
    duration = probe(output)
    if not MIN_SECONDS <= duration <= MAX_SECONDS: raise BuildError(f'{row["id"]} 编码后时长不在60–180秒')
    return {'duration_seconds': round(duration, 3), 'tempo': round(tempo, 6), 'target_words_per_minute': wpm}


def write_index(root: Path, rows: list[dict], valid: dict) -> None:
    atomic_json(root / 'index.json', {'schema_version': 1, 'updated_at': datetime.now(timezone.utc).isoformat(),
                                    'items': [valid[row['id']] for row in rows if row['id'] in valid]})


def generate(rows: list[dict], root: Path, args) -> int:
    ensure_no_links(root)
    for row in rows: safe_asset(root, row['file'])
    if root.resolve() == args.source.resolve() or root.exists() and not root.is_dir(): raise BuildError('输出须为素材目录')
    root.mkdir(parents=True, exist_ok=True)
    lock = root / '.build.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise BuildError('素材目录已有 .build.lock；请确认没有生成进程，清理遗留锁后重试') from exc
    try:
        with os.fdopen(fd, 'w') as stream: stream.write(str(os.getpid()))
        existing = load_index(root); valid = {}
        for row in rows:
            if row['id'] not in existing: continue
            try: validate_asset(existing[row['id']], row, root); valid[row['id']] = existing[row['id']]
            except BuildError: pass
        selected = rows[:args.limit] if args.limit is not None else rows
        failures, generated, resumed, piper = [], 0, 0, None
        for row in selected:
            identifier = row['id']
            if identifier in valid and not args.force:
                resumed += 1; print(f'{identifier}: 已验证，继续使用', flush=True); continue
            try:
                with tempfile.TemporaryDirectory(prefix='listening-', dir=root) as work:
                    work = Path(work); raw = work / ('speech.mp3' if args.backend == 'edge' else 'speech.wav')
                    text = spoken_text(row)
                    if args.backend == 'edge':
                        synthesis = asyncio.run(edge_speech(text, raw, args.voice))
                    else:
                        if piper is None:
                            if args.piper_model is None: raise BuildError('--backend piper 需要 --piper-model', code='PIPER_MODEL_REQUIRED')
                            piper = PiperSpeech(args.piper_model)
                        synthesis = piper.save(text, raw, row['grade'])
                    final = work / 'final.mp3'; timing = encode(raw, final, row)
                    synthesis.update({'speaker_labels_spoken': False, 'tempo': timing['tempo'], 'target_words_per_minute': timing['target_words_per_minute']})
                    entry = {**row, 'duration_seconds': timing['duration_seconds'], 'sha256': digest(final), 'synthesis': synthesis}
                    target = safe_asset(root, row['file']); target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(final, target); valid[identifier] = entry
                    write_index(root, rows, valid); generated += 1
                    print(f'{identifier}: 已生成 {entry["duration_seconds"]:.3f} 秒', flush=True)
            except Exception as exc:
                message = str(exc) if isinstance(exc, BuildError) else '语音生成失败，请检查语音引擎、模型文件和网络；未生成替代音频'
                code = exc.code if isinstance(exc, BuildError) else 'GENERATION_FAILED'
                failures.append({'id': identifier, 'error_type': type(exc).__name__, 'code': code, 'message': message})
                print(f'{identifier}: {type(exc).__name__} [{code}]；失败详情见 failures.json', file=sys.stderr, flush=True)
        # Even a partially completed run exposes only independently validated assets.
        write_index(root, rows, valid)
        atomic_json(root / 'failures.json', {'failed': failures, 'generated': generated, 'resumed': resumed, 'complete': len(valid) == len(rows)})
        print(json.dumps({'generated': generated, 'resumed': resumed, 'failed': len(failures), 'ready': len(valid), 'expected': len(rows)}, ensure_ascii=False))
        return 1 if failures else 0
    finally:
        lock.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_ROOT / 'curated.json')
    parser.add_argument('--output', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--backend', choices=('edge', 'piper'), default='edge')
    parser.add_argument('--voice', default='en-US-JennyNeural', help='Edge 英文音色')
    parser.add_argument('--piper-model', type=Path, help='本地已下载的 Piper .onnx 文件；不自动联网下载')
    parser.add_argument('--limit', type=int, help='仅生成前 N 篇，用于真实样本验证；完整交付仍须 verify-only')
    parser.add_argument('--force', action='store_true', help='明确重新生成所选条目；否则恢复已校验资产')
    parser.add_argument('--verify-only', action='store_true', help='只读校验全部文稿、MP3、时长和摘要；不导入语音引擎、不联网')
    args = parser.parse_args()
    try:
        rows = load_curated(args.source)
        if args.limit is not None and args.limit < 1: raise BuildError('--limit 须大于0')
        if args.verify_only:
            print(json.dumps(verify(rows, args.output), ensure_ascii=False)); return 0
        return generate(rows, args.output, args)
    except BuildError as exc:
        print(f'[{exc.code}] {exc}', file=sys.stderr); return 2
    except OSError as exc:
        print(f'文件操作失败（{type(exc).__name__}）；请检查目录权限和外部命令安装', file=sys.stderr); return 2


if __name__ == '__main__': raise SystemExit(main())
