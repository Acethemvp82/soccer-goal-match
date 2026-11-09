"""Today's fixtures stay visible across competitions and after kickoff."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from data_source import fetch_url
from extra_leagues import BASE,LEAGUES
from daily_fixtures import fetch_daily_fixtures
from match_observations import parse_match_observations
from model import parse_time

ET=ZoneInfo('America/New_York')

@st.cache_data(ttl=120,show_spinner=False)
def load_daily(date_string):return fetch_daily_fixtures(date_string)

@st.cache_data(ttl=120,max_entries=100,show_spinner=False)
def load_daily_summary(fixture):
    return {'summary':fetch_url(BASE+'all/summary?event='+str(fixture)),
            'asOf':datetime.now(ET).isoformat()}


def open_league(code,day):
    st.session_state['board_view']='Single league'
    st.session_state['league_selection']=code
    st.session_state['match_date' if code=='eng.1' else 'extra_date']=day


def render_daily_fixtures():
    st.subheader("Today's matches across competitions")
    st.caption('Cross-competition ESPN fixture feed. This includes live and completed matches and may differ from your sportsbook’s available markets. Fixture coverage does not guarantee player statistics or a scoring estimate.')
    today=datetime.now(ET).date()
    chosen=st.date_input('Fixture date',value=today,min_value=today-timedelta(days=1),max_value=today+timedelta(days=7),key='daily_fixture_date')
    if st.button('↻ Refresh today’s fixtures',key='daily_refresh'):
        load_daily.clear();load_daily_summary.clear()
    try:packet=load_daily(chosen.isoformat())
    except Exception:st.warning('Cross-competition fixture feed unavailable. Use Single league to check a competition directly.');return
    if packet['failures']:st.warning('Some fixture requests failed; the list may be incomplete. Refresh or check the competition directly.')
    games=packet['games']
    st.caption('Fixture feed retrieved '+parse_time(packet['asOf']).astimezone(ET).strftime('%b %d · %I:%M:%S %p ET')+' · refresh cache: 2 minutes.')
    if not games:st.info('No fixtures returned for this date. This does not confirm that no matches exist.');return
    search=st.text_input('Find today’s team or competition',key='daily_fixture_search')
    visible=[g for g in games if search.casefold() in (g['matchLabel']+' '+g['competitionLabel']).casefold()]
    records=[]
    for g in visible:
        status={'pre':'Scheduled','in':'LIVE','post':'FINAL'}.get(g['state'],'Status unavailable')
        score=f"{g['team_h_score']}–{g['team_a_score']}" if g['team_h_score'] is not None and g['team_a_score'] is not None else '—'
        records.append({'Kickoff ET':parse_time(g['kickoff_time']).astimezone(ET).strftime('%I:%M %p'),'Match':g['matchLabel'],'Competition':g['competitionLabel'],'Status':status,'Score':score,'Source clock':g['clock'] if g['state'] in ('in','post') else '—'})
    st.dataframe(pd.DataFrame(records),hide_index=True,use_container_width=True)
    st.caption('Live matches remain listed. Pregame probabilities, hammers and simulator runs are not generated retrospectively for matches that have started.')
    if not visible:st.info('No matches match this search.');return
    lookup={str(g['id']):g for g in visible}
    selected=st.selectbox('Match details / open league board',list(lookup),format_func=lambda k:lookup[k]['matchLabel'],key='daily_match_detail')
    if not st.checkbox('Load selected match details',key='daily_load_detail'):return
    game=lookup[selected]
    try:
        details=load_daily_summary(game['id'])
        observation=parse_match_observations(game,details['summary'])
    except Exception:st.warning('Verified match details unavailable. No player activity is being inferred.');return
    league=details['summary'].get('header',{}).get('league',{})
    code=league.get('slug')
    st.write('**'+league.get('name',game['competitionLabel'])+'** · '+game['matchLabel'])
    if code in {'eng.1',*LEAGUES}:
        st.button('Open this league’s board',key='daily_open_league',on_click=open_league,args=(code,chosen))
    else:st.info('This competition does not have a supported scorer board. Match observations are shown below when available.')
    st.caption('Match summary retrieved '+parse_time(details['asOf']).astimezone(ET).strftime('%I:%M:%S %p ET')+' · source clock '+str(observation['clock'])+'. Source data can lag.')
    if observation['rows']:st.dataframe(pd.DataFrame(observation['rows']).style.format(precision=0,na_rep='—'),hide_index=True,use_container_width=True)
    else:st.info('Player statistics not available for this match.')
