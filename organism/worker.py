from __future__ import annotations
import os, sys, json, time, pickle, random, argparse, tempfile, shutil
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path: sys.path.insert(0,ROOT)
from organism.state import OrganismState
from organism.curiosity import choose_topic, brave_search, expand_query_with_openai, infer_topics
from organism.nm_guard import evaluate
from organism.topology import rebuild
import molang_persist

STATE_PATH=os.environ.get('ORGANISM_STATE','data/organism_state.pkl')
SOM_PATH=os.environ.get('ORGANISM_SOM','data/curiosity_som.pkl')
MOLANG_PATH=os.environ.get('MOLANG_PKL','data/molang.pkl')

def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH,'rb') as f: return pickle.load(f)
        except Exception: pass
    return OrganismState()

def save_state(s):
    s.trim(); os.makedirs(os.path.dirname(STATE_PATH) or '.',exist_ok=True)
    tmp=STATE_PATH+'.tmp'
    with open(tmp,'wb') as f: pickle.dump(s,f)
    os.replace(tmp,STATE_PATH)

def load_identity():
    if not os.path.exists(MOLANG_PATH): return None
    try: return molang_persist.load_molang_bytes(open(MOLANG_PATH,'rb').read())
    except Exception as e:
        print('Molang PKL load warning:',e); return None

def ingest_result(state, topic, r):
    item={'id':state.uid((r.get('url','')+r.get('title',''))), 'topic':topic,
          'title':r.get('title','')[:300], 'text':r.get('text','')[:2400],
          'url':r.get('url',''), 'at':time.time()}
    if any(x.get('id')==item['id'] for x in state.observations): return None
    gate=evaluate(state,item); item.update(gate)
    state.observations.append(item)
    getattr(state, {'candidate':'candidates','quarantine':'quarantine','reject':'rejected'}[gate['status']]).append(item)
    reward=(gate['score']-.4) if gate['status']!='reject' else -.15
    state.touch_interest(topic,reward)
    for tag in infer_topics(item['title']+' '+item['text'],3):
        if tag!=topic: state.interests[tag]=max(0.0,state.interests.get(tag,0)*.99 + .03*max(0,reward))
    return item

def curiosity_cycle(state, deep=False):
    identity=load_identity(); prompt=identity.identity.to_system_prompt() if identity else ''
    topic=choose_topic(state, random.Random(time.time_ns()))
    query=expand_query_with_openai(topic,prompt) if deep else topic
    results=brave_search(query,os.environ.get('BRAVE_API_KEY'),count=int(os.environ.get('CURIOSITY_RESULTS','5')))
    accepted=[]
    for r in results:
        x=ingest_result(state,topic,r)
        if x: accepted.append(x)
    state.curiosity_history.append({'at':time.time(),'topic':topic,'query':query,'deep':deep,
                                    'found':len(results),'ingested':len(accepted)})
    return {'topic':topic,'query':query,'found':len(results),'ingested':len(accepted),
            'candidate':sum(x['status']=='candidate' for x in accepted),
            'quarantine':sum(x['status']=='quarantine' for x in accepted)}

def maintenance(state):
    # Decay interest: prevents one early fascination from permanently monopolizing exploration.
    for k in list(state.interests):
        state.interests[k]*=.997
        if state.interests[k]<.002: state.interests.pop(k,None)
    state.cycle+=1
    return rebuild(state,SOM_PATH)

def reflect(state):
    top=sorted(state.interests.items(),key=lambda kv:-kv[1])[:8]
    entry={'at':time.time(),'cycle':state.cycle,'top_interests':top,
           'candidate':len(state.candidates),'quarantine':len(state.quarantine),
           'rejected':len(state.rejected)}
    state.reflection_log.append(entry); return entry

def main(mode):
    s=load_state(); out={'mode':mode,'at':time.time()}
    if mode in ('hourly','all'):
        out['curiosity']=curiosity_cycle(s,deep=False); s.last_hourly_at=time.time()
        out['topology']=maintenance(s)
    if mode in ('nightly','all'):
        out['deep_curiosity']=curiosity_cycle(s,deep=True); s.last_nightly_at=time.time()
        out['topology_night']=maintenance(s); out['reflection']=reflect(s)
    save_state(s); print(json.dumps(out,ensure_ascii=False,indent=2,default=str)); return out

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--mode',choices=['hourly','nightly','all'],default='hourly')
    main(ap.parse_args().mode)
