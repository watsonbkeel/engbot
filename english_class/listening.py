"""Read-only, authenticated listening material catalogue. Never generates at request time."""
import json
import re
from pathlib import Path

class ListeningUnavailable(RuntimeError):
    pass

class ListeningLibrary:
    def __init__(self,root): self.root=Path(root).resolve()

    def load(self):
        try:
            raw=json.loads((self.root/'index.json').read_text(encoding='utf-8'))
            items=raw['items']
            if not isinstance(items,list): raise ValueError('items must be a list')
            ids=set(); checked=[]
            for row in items:
                if not isinstance(row,dict): raise ValueError('invalid item')
                ident=row['id']
                if not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',ident) or ident in ids:
                    raise ValueError('invalid or duplicate id')
                if type(row['grade']) is not int or not 1<=row['grade']<=9: raise ValueError('invalid grade')
                if row['type'] not in ('story','dialogue'): raise ValueError('invalid type')
                if not isinstance(row['title'],str) or not row['title'].strip(): raise ValueError('missing title')
                if not isinstance(row['transcript'],str) or not row['transcript'].strip(): raise ValueError('missing transcript')
                if type(row['duration_seconds']) not in (int,float) or not 60<=row['duration_seconds']<=180:
                    raise ValueError('audio must be 60–180 seconds')
                if not isinstance(row['file'],str): raise ValueError('invalid file')
                path=(self.root/row['file']).resolve()
                if not path.is_relative_to(self.root) or path.suffix.lower()!='.mp3' or not path.is_file():
                    raise ValueError('audio unavailable')
                ids.add(ident); checked.append({**row,'_path':path})
            return checked
        except (OSError,ValueError,KeyError,TypeError) as exc:
            raise ListeningUnavailable('听力素材尚未完整安装或索引损坏，请运行素材生成工具并检查结果') from exc

    def catalogue(self,grade):
        result=[]
        for row in self.load():
            if row['grade']!=grade: continue
            result.append({k:row[k] for k in ('id','grade','type','title','duration_seconds','transcript')}|
                          {'audio_url':f"/api/listening/{row['id']}/audio"})
        return {'items':result,'grade':grade}

    def audio(self,ident):
        return next((x['_path'] for x in self.load() if x['id']==ident),None)
