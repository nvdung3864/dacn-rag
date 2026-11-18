"""Request-local generation hooks and incremental decoding of a JSON answer."""
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar

HOOK=ContextVar('generation_hook',default=None)

class GenerationCancelled(Exception):pass

@contextmanager
def generation_hook(callback,cancel):
    token=HOOK.set((callback,cancel))
    try:yield
    finally:HOOK.reset(token)

def answer_prefix(raw):
    match=re.search(r'"answer"\s*:\s*"',raw)
    if not match:return ''
    chars=[];index=match.end()
    while index<len(raw):
        char=raw[index]
        if char=='"':break
        if char=='\\':
            if index+1>=len(raw):break
            end=index+(6 if raw[index+1]=='u' else 2)
            if end>len(raw):break
            try:char=json.loads('"'+raw[index:end]+'"')
            except ValueError:break
            index=end
        else:index+=1
        chars.append(char)
    # Drafts never turn source IDs into clickable links. Hide incomplete IDs.
    text=''.join(chars).encode('utf-16','surrogatepass').decode('utf-16',errors='ignore')
    return re.sub(r'\[S[^\]]*(?:\]|$)','',text)

def read_generation(response,local):
    hook=HOOK.get();raw='';last='';final={};done=False
    for line in response.iter_lines():
        if hook and hook[1].is_set():raise GenerationCancelled()
        if not line:continue
        if not local:
            if not line.startswith('data:'):continue
            line=line[5:].strip()
            if line=='[DONE]':done=True;break
        try:item=json.loads(line)
        except ValueError:raise ValueError('Provider stream contains invalid JSON.')
        if item.get('error'):raise ValueError('Provider interrupted generation.')
        if local:
            raw+=item.get('message',{}).get('content','')
            if item.get('done'):done=True;final=item
        else:
            choices=item.get('choices',[])
            if choices:raw+=choices[0].get('delta',{}).get('content') or ''
            if item.get('usage'):final['usage']=item['usage']
        if len(raw)>200000:raise ValueError('Provider answer exceeded stream limit.')
        prefix=answer_prefix(raw)
        if hook and prefix!=last:
            hook[0](prefix);last=prefix
    if not done:raise ValueError('Provider stream ended before completion.')
    if local:return {**final,'message':{'content':raw}}
    return {**final,'choices':[{'message':{'content':raw}}]}
