#!/usr/bin/env bash
set -euo pipefail

# Preserve a caller's relative executable path before changing directory.
if [[ -n "${PYTHON:-}" && "$PYTHON" == */* && "$PYTHON" != /* ]]; then
  PYTHON="$PWD/$PYTHON"
fi
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$ROOT"
if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
  else
    PYTHON=python3
  fi
fi
if ! PYTHON_EXECUTABLE=$(command -v -- "$PYTHON") || [[ ! -x "$PYTHON_EXECUTABLE" ]]; then
  printf '找不到可执行的 Python：%s\n' "$PYTHON" >&2
  printf '请安装 Python 3.11+，创建 .venv，或设置 PYTHON=/解释器的完整路径。\n' >&2
  exit 2
fi
# Do not realpath the executable: a venv python may be a symlink to system Python.
PYTHON="$PYTHON_EXECUTABLE"
export PYTHON

if ! "$PYTHON" - <<'PY'
import platform
import sys

print(f'Python {platform.python_version()} ({sys.executable})', flush=True)
if sys.version_info < (3, 11):
    raise SystemExit('测试需要 Python 3.11 或更新版本。')
try:
    import pytest
except ImportError:
    raise SystemExit('所选 Python 无法导入 pytest。')
print(f'pytest {pytest.__version__}', flush=True)
PY
then
  printf '请在 Python 3.11+ 环境中安装测试依赖：\n  "%s" -m pip install -r requirements-dev.txt\n' "$PYTHON" >&2
  exit 2
fi

missing_tools=0
for tool in node ffmpeg ffprobe; do
  if ! command -v -- "$tool" >/dev/null 2>&1; then
    printf '缺少测试工具：%s\n' "$tool" >&2
    missing_tools=1
  fi
done
if [[ "$missing_tools" == 1 ]]; then
  printf '请安装 Node.js 和 ffmpeg（包含 ffprobe），并加入 PATH。\n' >&2
  printf 'macOS 可使用 brew install node ffmpeg；Linux 请使用系统包管理器。\n' >&2
  exit 2
fi
node_version=$(node --version)
ffmpeg_version=$(ffmpeg -version)
ffprobe_version=$(ffprobe -version)
printf 'Node.js %s\n%s\n%s\n' "$node_version" "${ffmpeg_version%%$'\n'*}" "${ffprobe_version%%$'\n'*}"

"$PYTHON" -m compileall -q english_class pi scripts tests
"$PYTHON" -m pytest -q
node --test tests_js/*.test.js
find miniprogram -name '*.js' -print0 | xargs -0 -n1 node --check
for script in scripts/*.sh; do bash -n "$script"; done
