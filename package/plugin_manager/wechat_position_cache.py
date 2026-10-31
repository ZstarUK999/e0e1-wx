"""Small persistent semantic positions; never persist native object pointers."""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile


def cache_path():
    base=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData'/'Local')))
    return base/'e0e1'/'e0e1-wx-plugins'/'wechat_launch_positions.json'


def load():
    try:
        path=cache_path()
        if path.stat().st_size>65536:return {}
        value=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value,dict) or value.get('schema')!=1:return {}
        return {k:v for k,v in value.items() if k=='schema' or k in ('native','entry') and isinstance(v,dict)}
    except (OSError,ValueError):return {}


def save(kind,value):
    if not isinstance(value,dict):return
    if kind=='native':
        required={'pid','processCreatedAt','hwnd','origin','clientSize','controls'}
        if not required.issubset(value) or not value['controls']:return
        value={k:value[k] for k in required | {'version','scaleX','scaleY','layout'} if k in value}
        value['controls']=[{k:c[k] for k in ('label','type','screenCenter','localRect') if k in c}
                           for c in value['controls']]
    elif kind=='entry':
        if not {'pid','processStart','hwnd','width','height','dpi','x','y','runtimeId'}.issubset(value):return
    else:raise ValueError('Unknown position cache')
    data=load()
    previous=data.get('native',{})
    if kind=='native' and all(previous.get(k)==value.get(k) for k in
            ('pid','processCreatedAt','hwnd','clientSize','version','scaleX','scaleY')):
        # A different page may omit 小程序; keep its last known position for the fast path.
        merged=[]
        labels={c.get('label') for c in value['controls']}
        for control in previous.get('controls',[]):
            if control.get('label') not in ('发现','小程序') or control.get('label') in labels:continue
            center=control.get('screenCenter')
            if not center:continue
            merged.append({**control,'screenCenter':{
                axis:center[axis]-previous['origin'][axis]+value['origin'][axis] for axis in ('x','y')}})
        value['controls']=merged+value['controls']
    data.update(schema=1);data[kind]=value
    path=cache_path();path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix=path.name,suffix='.tmp')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False)
        os.replace(tmp,path)
    finally:
        if Path(tmp).exists():Path(tmp).unlink()
