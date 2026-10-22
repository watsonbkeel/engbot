#!/usr/bin/env python3
"""Build the canonical six-page app; optionally merge into a new host-project copy."""
from __future__ import annotations
import argparse
import shutil
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from english_class.sources import merge_miniprogram


def build(output:Path,source:Path|None=None,connection:Path|None=None) -> Path:
    overlay=ROOT/'miniprogram';out=output.resolve()
    if connection is not None and (not connection.is_file() or connection.is_symlink()):
        raise ValueError('连接文件必须是本人生成的普通 english-env.local.js 文件')
    if out.exists() or out==overlay or overlay in out.parents:
        raise ValueError('输出目录必须是源码之外尚不存在的新目录')
    if source is not None:
        merge_miniprogram(source,overlay,out)
    else:
        if any(p.is_symlink() for p in overlay.rglob('*')): raise ValueError('陪练源码含符号链接，停止构建')
        shutil.copytree(overlay,out,ignore=shutil.ignore_patterns('.git','node_modules','__pycache__','.DS_Store','project.private.config.json','*.local.js','.env','.env.*'))
    if connection is not None:
        target=out/'utils/english-env.local.js';shutil.copy2(connection,target);target.chmod(0o600)
    return out


def main() -> int:
    parser=argparse.ArgumentParser(description='默认输出独立六页小程序；可选非破坏性合并到原项目的新副本')
    parser.add_argument('--source',type=Path,help='可选：原项目有 app.json 的根目录；保留其 app.js 与 tabBar')
    parser.add_argument('--output',type=Path,required=True,help='尚不存在的输出目录')
    parser.add_argument('--connection',type=Path,help='可选：显式加入本人连接文件；此输出不得公开分享')
    args=parser.parse_args()
    try:
        output=build(args.output,args.source,args.connection)
        print('已生成：'+str(output)+'；请在微信开发者工具选择本人 AppID 并配置合法 HTTPS 域名。')
        return 0
    except (ValueError,OSError) as exc:
        print(str(exc),file=sys.stderr);return 1


if __name__=='__main__': raise SystemExit(main())
