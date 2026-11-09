"""Separate Streamlit panel; original scores, order and hammer criteria are untouched."""
BUILD_ID='2026-11-09-simulator-2'
from datetime import datetime, timezone
import pandas as pd
import streamlit as st
from model import parse_time
from simulation import RUNS, eligibility_issue, row_identity, signature, simulate_rows


def render_simulator(rows,key):
    with st.expander('10,000-run scorer simulator'):
        st.caption('Player scoring scenarios using the existing model, conditional on the player appearing. Starter/substitute role is sampled, then goals are drawn from its Poisson scoring rate. These are independent player simulations, not a full-match engine, scoreline forecast, or parlay calculator. Simulating more times does not validate the underlying model.')
        if not st.checkbox('Enable scorer simulator',key=key+'sim_enable'):return
        lookup={str(r.get('league','eng.1'))+':'+str(r['fixture']):r for r in rows}
        if not lookup:st.info('No player rows available for simulation.');return
        match=st.selectbox('Match to simulate',list(lookup),format_func=lambda k:lookup[k].get('league','eng.1')+' · '+lookup[k]['team']+' vs '+lookup[k]['opponent'],key=key+'sim_match')
        starter_only=st.checkbox('Simulate confirmed starters only',key=key+'sim_starters')
        delta=st.selectbox('Minutes scenario',[0,-15,15],format_func=lambda d:'Current role minutes' if d==0 else f'{d:+d} minutes per role (capped at 0–90)',key=key+'sim_minutes')
        now=datetime.now(timezone.utc);eligible=[];excluded=[]
        for row in rows:
            if str(row.get('league','eng.1'))+':'+str(row['fixture'])!=match:continue
            issue=eligibility_issue(row,now)
            if not issue and starter_only and row.get('lineup')!='Confirmed starter':issue='Not a confirmed starter'
            if issue:excluded.append({'Player':row.get('name',str(row['id'])),'Reason':issue})
            else:eligible.append(row)
        st.caption(f'{len(eligible)} eligible players · {len(excluded)} excluded from this view. Uses the board’s current player filters. Unconfirmed roles and bench estimates are conditional on an appearance; no probability of appearing is supplied.')
        if excluded:
            with st.expander('Excluded simulation rows'):st.dataframe(pd.DataFrame(excluded),hide_index=True,use_container_width=True)
        if not eligible:st.info('No current, complete pregame estimates match these settings. Refresh data or adjust the filters.');return
        fingerprint=signature(eligible,delta)
        result_key=key+'sim_result'
        if st.button('Run 10,000 scoring simulations',key=key+'sim_run'):
            try:
                with st.spinner('Simulating player goal counts…'):
                    run_time=datetime.now(timezone.utc)
                    result=simulate_rows(eligible,run_time,delta)
                st.session_state[result_key]={'signature':fingerprint,'rows':result,'createdAt':run_time.isoformat()}
            except ValueError as exc:
                st.session_state.pop(result_key,None);st.warning(str(exc));return
        saved=st.session_state.get(result_key)
        if not saved:return
        age=(datetime.now(timezone.utc)-parse_time(saved['createdAt'])).total_seconds()
        if saved['signature']!=fingerprint or not 0<=age<=600:
            st.info('Inputs/settings changed or this run is more than ten minutes old. Run the simulation again.');return
        result_lookup={row_identity(r):r for r in saved['rows']}
        ordered_results=[result_lookup[row_identity(r)] for r in eligible]
        records=[]
        for r in ordered_results:
            records.append({'Board league rank':r['overallRank'],'Team rank':r['teamRank'],'🔨':r['hammer'],'Player':r['name'],'Team':r['team'],'Lineup':r['lineup'],'Board Anytime':100*r['modelProbability'],'Scenario Anytime':100*r['scenarioProbability'],'Simulated Anytime':100*r['simulatedProbability'],'0 goals':100*r['zeroGoals']/RUNS,'1 goal':100*r['oneGoal']/RUNS,'2+ goals':100*r['multipleGoals']/RUNS,'Avg goals':r['meanGoals'],'Sampling ± pp':r['samplingMarginPP']})
        config={c:st.column_config.NumberColumn(format='%.1f%%') for c in ['Board Anytime','Scenario Anytime','Simulated Anytime','0 goals','1 goal','2+ goals']}
        config['Avg goals']=st.column_config.NumberColumn(format='%.2f')
        config['Sampling ± pp']=st.column_config.NumberColumn(format='%.2f',help='Approximate 95% Monte Carlo sampling margin in percentage points. It measures simulation noise, not predictive uncertainty.')
        st.dataframe(pd.DataFrame(records),hide_index=True,use_container_width=True,column_config=config)
        st.caption('Keeps the board order. Scenario Anytime is the exact calculation for the selected minutes; Simulated Anytime should be close, with random sampling noise. Sampling ± pp is approximate simulation precision, not a confidence interval for real scoring ability. No simulation result changes a hammer or board rank.')
        st.caption('Run captured '+saved['createdAt']+' · Fixed seed for reproducible results. Each player uses 10,000 runs; outcomes are not combined into a match result.')
        st.download_button('Download simulation results',pd.DataFrame(ordered_results).to_csv(index=False).encode('utf-8-sig'),file_name='soccer-scorer-simulation.csv',mime='text/csv',key=key+'sim_export')
