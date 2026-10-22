"""Reproducible imports of the user's open-source projects; no invented word list."""
from __future__ import annotations
import hashlib
import io
import json
import shutil
import stat
import urllib.request
import zipfile
from pathlib import Path

WORDMASTER_COMMIT='4701d5bc72097c8851b180bf6025fb8b9db12ae4'
AIBOT_COMMIT='cd5b34c446d5134c6346f290f7513380edba84a5'
DICTIONARY_BLOB='ea9b65ea1c1ae6e4b871bbd27f8d46796097d8cc'


def git_blob_sha(data:bytes) -> str:
    return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()


def verify_blob(data:bytes,expected:str):
    actual=git_blob_sha(data)
    if actual!=expected: raise ValueError(f'原词库摘要不一致：期望{expected}，实际{actual}。未导入这个文件。')


def fetch_bytes(url:str,max_bytes:int=100_000_000) -> bytes:
    req=urllib.request.Request(url,headers={'User-Agent':'WordMaster-English-Class/0.1.0','Accept':'application/vnd.github.raw+json'})
    with urllib.request.urlopen(req,timeout=90) as response:
        chunks=[];size=0
        while True:
            chunk=response.read(65536)
            if not chunk: break
            size+=len(chunk)
            if size>max_bytes: raise ValueError('下载内容超过允许大小')
            chunks.append(chunk)
    return b''.join(chunks)


def import_dictionary(destination:Path,source:Path|None=None) -> dict:
    from .dictionary import Dictionary,parse_source
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    if source is not None:
        raw=Path(source).read_bytes();origin=str(Path(source).resolve());locked=False
    else:
        urls=[f'https://raw.githubusercontent.com/watsonbkeel/WordMaster_SZ/{WORDMASTER_COMMIT}/utils/fullDictionary.js',
              f'https://api.github.com/repos/watsonbkeel/WordMaster_SZ/contents/utils/fullDictionary.js?ref={WORDMASTER_COMMIT}']
        errors=[];raw=None
        for url in urls:
            try:
                candidate=fetch_bytes(url,20_000_000)
                verify_blob(candidate,DICTIONARY_BLOB)
                raw=candidate;origin=url;break
            except Exception as exc: errors.append(type(exc).__name__+': '+str(exc))
        if raw is None:
            raise ValueError('无法下载锁定版本原词库。可从你现有WordMaster_SZ目录导入：python3 scripts/prepare_sources.py --dictionary /路径/utils/fullDictionary.js\n'+ '\n'.join(errors))
        locked=True
    rows=parse_source(raw.decode('utf-8-sig'))
    temp=destination/'dictionary.json.importing'
    temp.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    try: dictionary=Dictionary(temp)
    except Exception:
        temp.unlink(missing_ok=True);raise
    raw_path=destination/'fullDictionary.js'
    raw_path.write_bytes(raw)
    temp.replace(destination/'dictionary.json')
    metadata={'origin':origin,'repository':'watsonbkeel/WordMaster_SZ','pinned_commit':WORDMASTER_COMMIT if locked else None,
              'git_blob_sha':git_blob_sha(raw),'sha256':hashlib.sha256(raw).hexdigest(),'records':len(rows),
              'elementary_records':sum(1 for r in rows if r['grade']<=6),
              'unit_policy':'unit=0 whole semester; positive unit is ordered group of 10, not textbook unit'}
    (destination/'dictionary-source.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    return metadata


def extract_archive(data:bytes,destination:Path):
    root=Path(destination).resolve()
    if root.exists(): raise ValueError('解压目标已存在；不覆盖')
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        if sum(i.file_size for i in z.infolist())>500_000_000 or len(z.infolist())>30000:
            raise ValueError('压缩包展开后过大')
        for info in z.infolist():
            if '\\' in info.filename: raise ValueError('拒绝异常压缩路径')
            target=(root/info.filename).resolve()
            if root not in target.parents and target!=root: raise ValueError('拒绝越界压缩路径')
            if stat.S_ISLNK(info.external_attr>>16): raise ValueError('拒绝压缩包中的软链接')
        root.mkdir(parents=True)
        z.extractall(root)


def download_upstreams(root:Path):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    for repo,commit in [('WordMaster_SZ',WORDMASTER_COMMIT),('aibot',AIBOT_COMMIT)]:
        dest=root/repo
        if dest.exists(): continue
        raw=fetch_bytes(f'https://codeload.github.com/watsonbkeel/{repo}/zip/{commit}')
        stage=root/(repo+'-extract')
        extract_archive(raw,stage)
        children=list(stage.iterdir())
        if len(children)!=1 or not children[0].is_dir(): raise ValueError('仓库压缩结构不符合预期')
        children[0].rename(dest);stage.rmdir()
        (root/(repo+'-source.json')).write_text(json.dumps({'repository':'watsonbkeel/'+repo,'commit':commit,'archive_sha256':hashlib.sha256(raw).hexdigest()},indent=2))


def merge_miniprogram(source:Path,overlay:Path,destination:Path):
    """Add the canonical six-page app to a new copy; never replace host routes/files."""
    src=Path(source).resolve();overlay=Path(overlay).resolve();dest=Path(destination).resolve()
    if dest.exists() or dest==src or src in dest.parents or overlay==dest or overlay in dest.parents:
        raise ValueError('输出目录须为原项目和陪练源码之外的新目录；不覆盖原文件')
    cfg_path=src/'app.json'
    if not cfg_path.is_file(): raise ValueError('原项目目录中找不到app.json；请选择小程序根目录')
    cfg=json.loads(cfg_path.read_text(encoding='utf-8'))
    original_pages=list(cfg.get('pages',[]))
    if not original_pages: raise ValueError('原项目没有pages配置')
    additions=json.loads((overlay/'app.json').read_text(encoding='utf-8')).get('pages',[])
    if not additions: raise ValueError('陪练源码没有pages配置')
    page_dirs=[]
    for page in additions:
        rel=Path(page)
        if not isinstance(page,str) or rel.is_absolute() or '..' in rel.parts or rel.parts[0]!='pages':
            raise ValueError('陪练页面路由不合法')
        folder=rel.parent
        if page in original_pages or (src/folder).exists():
            raise ValueError(f'页面同名冲突：{folder}；请使用干净副本，或手工改名后合并')
        if not (overlay/rel).with_suffix('.js').is_file(): raise ValueError(f'陪练页面缺少脚本：{page}')
        if folder not in page_dirs: page_dirs.append(folder)
    helpers=[f for f in (overlay/'utils').rglob('*') if f.is_file() and not f.name.endswith('.local.js')]
    for helper in helpers:
        rel=helper.relative_to(overlay)
        if (src/rel).exists(): raise ValueError(f'工具文件同名冲突：{rel}；未复制任何文件')
    # Do not follow links into files outside either input project.
    if any(p.is_symlink() for tree in (src,overlay) for p in tree.rglob('*')):
        raise ValueError('输入项目含符号链接，请先提供不含链接的完整副本')
    ignore=shutil.ignore_patterns('.git','node_modules','.DS_Store','project.private.config.json','.env','.env.*','.venv','__pycache__','*.local.js')
    shutil.copytree(src,dest,ignore=ignore)
    for folder in page_dirs: shutil.copytree(overlay/folder,dest/folder,ignore=ignore)
    for helper in helpers:
        target=dest/helper.relative_to(overlay);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(helper,target)
    cfg['pages']=additions+original_pages
    (dest/'app.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tabs=[x['pagePath'] for x in cfg.get('tabBar',{}).get('list',[])]
    home=tabs[0] if tabs else original_pages[0]
    origin={'home':home,'isTab':home in tabs,'embedded':True,'tabPages':tabs}
    (dest/'utils'/'english-origin.js').write_text('module.exports = '+json.dumps(origin,ensure_ascii=False)+'\n',encoding='utf-8')
    profile=dest/'pages'/'profile'/'index.wxml'
    if profile.exists():
        with profile.open('a',encoding='utf-8') as f:
            f.write('\n<!-- English Class additive entry -->\n<navigator url="/pages/today/index" style="margin:24rpx;padding:24rpx;background:#eaf0fa;border-radius:12rpx;">我的英语陪练 →</navigator>\n')
