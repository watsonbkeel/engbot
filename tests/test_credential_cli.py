"""Run the actual CLI and the install/provision scripts' CLI command boundary."""
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from english_class.dictionary import Dictionary
from english_class.store import Store

ROOT = Path(__file__).resolve().parents[1]


def test_cli_reads_public_environment_without_executing_shell_text(tmp_path, dictionary_path):
    database = tmp_path / 'state.sqlite3'
    key_path = tmp_path / 'separate secrets' / 'master.key'
    marker = tmp_path / 'must-not-exist'
    env_path = tmp_path / 'public.env'
    env_path.write_text(f'DATABASE_PATH="{database}"\nDICTIONARY_PATH="{dictionary_path}"\n'
                        f'LLM_SECRET_KEY_FILE="{key_path}"\nUNUSED_COMMAND=$(touch {marker})\n')
    result = subprocess.run([sys.executable, '-m', 'english_class.cli', '--env', str(env_path), 'init'],
                            cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert database.exists() and key_path.exists()
    assert not Path(str(database) + '.key').exists()
    assert not marker.exists()


def _cli_command(script_path):
    lines = script_path.read_text().splitlines()
    start = next(index for index, line in enumerate(lines) if '-m english_class.cli' in line)
    command = lines[start]
    while command.endswith('\\'):
        start += 1
        command = command[:-1] + ' ' + lines[start].strip()
    return command


@pytest.mark.parametrize('script', ['install_server.sh', 'create_student.sh'])
def test_deployment_cli_command_uses_the_same_custom_key_as_public_service(tmp_path, dictionary_path, script):
    # Only privileged installation/account steps are excluded. Execute the real
    # script's CLI command against temporary deployment paths and the real CLI.
    install_root = tmp_path / 'installed'
    (install_root / '.venv' / 'bin').mkdir(parents=True)
    (install_root / '.venv' / 'bin' / 'python').symlink_to(sys.executable)
    (install_root / 'data').mkdir()
    (install_root / 'data' / 'dictionary.json').write_bytes(dictionary_path.read_bytes())
    database = tmp_path / 'custom-public.sqlite3'
    fixed_default = tmp_path / 'class.sqlite3'
    key_path = tmp_path / 'separate secrets' / 'master.key'
    env_path = tmp_path / 'public.env'
    env_path.write_text(f'LLM_SECRET_KEY_FILE="{key_path}"\nDATABASE_PATH="{database}"\n'
                        f'DICTIONARY_PATH="{dictionary_path}"\n')
    if script == 'create_student.sh':
        existing = Store(database, Dictionary(dictionary_path), credential_key_path=key_path)
        existing.add_student('s001', 'fictional-first-parent-token', 'fictional-first-brain-token')
        existing.save_llm('s001', 'https://fixture.example/v1', 'test-model', 'fictional-stored-key-for-cli')
    command = _cli_command(ROOT / 'scripts' / script)
    command = command.replace('/etc/english-class/public.env', shlex.quote(str(env_path)))
    command = command.replace('/var/lib/english-class/class.sqlite3', shlex.quote(str(fixed_default)))
    command = command.replace('/var/lib/english-class/provision/$SID', str(tmp_path / 'provision' / 's002'))
    shell = 'runuser() { test "$1" = -u && test "$3" = -- || return 99; shift 3; "$@"; }\n' + command
    env = {**os.environ, 'ROOT': str(install_root), 'DEST': str(install_root), 'SID': 's002', 'PORT': '9102',
           'PUBLIC_PORT': '18090', 'PUBLIC_EXTERNAL': 'https://class.example',
           'BRAIN_EXTERNAL': 'https://class.example/students/s002', 'PYTHONPATH': str(ROOT)}
    env.pop('LLM_SECRET_KEY_FILE', None)
    env.pop('BASH_ENV', None)
    result = subprocess.run(['bash', '-euc', shell], env=env, text=True, capture_output=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    assert database.exists() and not fixed_default.exists()
    assert key_path.exists() and not Path(str(database) + '.key').exists()
    reopened = Store(database, Dictionary(dictionary_path), credential_key_path=key_path)
    if script == 'create_student.sh':
        assert reopened.llm('s001')['api_key'] == 'fictional-stored-key-for-cli'
        assert 's002' in reopened.student_ids()
