"""Listening build diagnostics and symlink boundaries, using real filesystem paths."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest

from scripts import make_listening as listening


@pytest.fixture
def asset_entry():
    source = listening.DEFAULT_ROOT
    entry = json.loads((source / 'index.json').read_text(encoding='utf-8'))['items'][0]
    original = json.loads((source / 'curated.json').read_text(encoding='utf-8'))['items'][0]
    return entry, original


def assert_code(expected, action):
    with pytest.raises(listening.BuildError) as caught:
        action()
    assert getattr(caught.value, 'code', None) == expected
    return caught.value


def test_missing_audio_has_stable_code(tmp_path, asset_entry):
    entry, original = asset_entry
    error = assert_code('ASSET_MISSING', lambda: listening.validate_asset(entry, original, tmp_path.resolve()))
    assert '音频缺失' in str(error)


def test_tampered_audio_has_stable_code(tmp_path, asset_entry):
    entry, original = asset_entry
    root = tmp_path.resolve()
    target = root / entry['file']
    target.parent.mkdir()
    target.write_bytes(b'corrupt')
    error = assert_code('ASSET_DIGEST_MISMATCH', lambda: listening.validate_asset(entry, original, root))
    assert '音频摘要不一致' in str(error)


def test_only_trusted_temporary_fixture_is_canonicalized(tmp_path, asset_entry):
    """The alias stays forbidden to production; its newly created fixture is resolved."""
    entry, original = asset_entry
    base = tmp_path.resolve()
    physical = base / 'physical'
    physical.mkdir()
    alias = base / 'system-temp-alias'
    alias.symlink_to(physical, target_is_directory=True)
    with tempfile.TemporaryDirectory(dir=alias) as temporary:
        raw_root = Path(temporary)
        root = raw_root.resolve()
        target = root / entry['file']
        target.parent.mkdir()
        target.write_bytes(b'corrupt')
        assert_code('PATH_SYMLINK', lambda: listening.safe_asset(raw_root, entry['file']))
        assert_code('ASSET_DIGEST_MISMATCH', lambda: listening.validate_asset(entry, original, root))


@pytest.mark.parametrize('kind', ['root', 'directory', 'audio'])
@pytest.mark.parametrize('destination', ['inside', 'outside', 'dangling'])
def test_asset_symbolic_links_are_rejected(tmp_path, asset_entry, kind, destination):
    entry, _ = asset_entry
    base = tmp_path.resolve()
    root = base / 'assets'
    root.mkdir()
    outside = base / 'outside'
    outside.mkdir()
    if kind == 'root':
        link = base / 'asset-link'
        target = root if destination == 'inside' else outside
        if destination == 'dangling':
            target = base / 'absent-root'
        link.symlink_to(target, target_is_directory=True)
        root = link
    elif kind == 'directory':
        target = (root if destination == 'inside' else outside) / 'actual-grade'
        if destination != 'dangling':
            target.mkdir()
        (root / 'g1').symlink_to(target, target_is_directory=True)
    else:
        (root / 'g1').mkdir()
        target = (root if destination == 'inside' else outside) / 'actual.mp3'
        if destination != 'dangling':
            target.write_bytes(b'unchanged')
        (root / entry['file']).symlink_to(target)
    assert_code('PATH_SYMLINK', lambda: listening.safe_asset(root, entry['file']))


@pytest.mark.parametrize('filename', ['index.json', 'failures.json'])
@pytest.mark.parametrize('dangling', [False, True])
def test_atomic_metadata_rejects_symbolic_links_without_touching_target(tmp_path, filename, dangling):
    root = tmp_path.resolve()
    target = root / 'original.json'
    if not dangling:
        target.write_bytes(b'{"unchanged": true}')
    metadata = root / filename
    metadata.symlink_to(target)
    assert_code('PATH_SYMLINK', lambda: listening.atomic_json(metadata, {'items': []}))
    assert metadata.is_symlink()
    assert target.exists() is (not dangling)
    if not dangling:
        assert target.read_bytes() == b'{"unchanged": true}'
    assert list(root.glob(filename + '.*.tmp')) == []


def test_cli_rejects_alias_before_creating_output_with_stable_code(tmp_path):
    base = tmp_path.resolve()
    physical = base / 'physical'
    physical.mkdir()
    alias = base / 'alias'
    alias.symlink_to(physical, target_is_directory=True)
    output = alias / 'assets'
    result = subprocess.run(
        [sys.executable, str(listening.ROOT / 'scripts/make_listening.py'),
         '--backend', 'piper', '--piper-model', str(base / 'missing.onnx'),
         '--output', str(output), '--limit', '1'],
        cwd=listening.ROOT, text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 2
    assert '[PATH_SYMLINK]' in result.stderr
    assert '素材输出路径不能经过符号链接' in result.stderr
    assert not output.exists()
