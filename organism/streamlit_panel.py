"""Drop-in Streamlit panel. Call render_organism_panel() from molang app.py."""
import os, pickle

def render_organism_panel():
    import streamlit as st
    p=os.environ.get('ORGANISM_STATE','data/organism_state.pkl')
    st.subheader('🌱 Digital Organism')
    if not os.path.exists(p): st.info('worker state가 아직 없습니다.'); return
    with open(p,'rb') as f: s=pickle.load(f)
    c1,c2,c3=st.columns(3); c1.metric('cycles',s.cycle); c2.metric('observations',len(s.observations)); c3.metric('quarantine',len(s.quarantine))
    st.write('관심 지형', sorted(s.interests.items(),key=lambda kv:-kv[1])[:15])
    if s.curiosity_history: st.json(s.curiosity_history[-1])
