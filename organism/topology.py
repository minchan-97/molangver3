from __future__ import annotations
import os, pickle, numpy as np
from .embedder import hashed_embedding
from .som import SOM

class Rec:
    def __init__(self, rid): self.rec_id=rid; self.year=None; self.code=None

def rebuild(state, path, grid=(10,10), dim=64):
    items=[x for x in state.observations if x.get('status') in ('candidate','accepted')]
    if len(items)<4: return {'trained':False,'n':len(items)}
    X=np.stack([hashed_embedding((x.get('title','')+' '+x.get('text','')),dim) for x in items])
    s=SOM(grid=grid,dim=dim,seed=42)
    s.train(X,iters=min(2500,max(400,len(items)*30)),seed=42)
    s.assign(X,[Rec(x['id']) for x in items])
    os.makedirs(os.path.dirname(path),exist_ok=True); s.save(path)
    return {'trained':True,'n':len(items),'occupied':len(s.node_rec_ids),
            'mean_qe':float(np.mean([s.qe[i] for i in s.node_rec_ids]))}
