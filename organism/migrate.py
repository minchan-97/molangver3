"""Copy an existing Molang PKL without mutating it, and initialize organism state."""
import os, sys, shutil, pickle, argparse
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,ROOT)
from organism.state import OrganismState
import molang_persist
ap=argparse.ArgumentParser(); ap.add_argument('source'); ap.add_argument('--dest',default='data/molang.pkl'); a=ap.parse_args()
raw=open(a.source,'rb').read(); u=molang_persist.load_molang_bytes(raw)  # compatibility check
os.makedirs(os.path.dirname(a.dest) or '.',exist_ok=True); shutil.copy2(a.source,a.dest)
os.makedirs('data',exist_ok=True)
sp='data/organism_state.pkl'
if not os.path.exists(sp):
    with open(sp,'wb') as f: pickle.dump(OrganismState(),f)
print('OK:',a.dest,'trees=',len(u.registry.trees),'facts=',len(u.identity.learned_facts),'episodes=',len(u.identity.episodic))
