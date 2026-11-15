"""Today's fixtures stay visible across competitions and after kickoff."""
BUILD_ID = 'match-coverage-1'
from datetime import datetime,timedelta
import re
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

@st.cache_data(ttl=120,max_entries=200,show_spinner=False)
def load_daily_summary(fixture, code='all'):
    return {'summary':fetch_url(BASE+code+'/summary?event='+str(fixture)),
            'asOf':datetime.now(ET).isoformat()}


def has_player_stats(observation):
    return any(row[field] is not None for row in observation['rows']
               for field in ('Goals', 'Shots', 'Shots on target'))


def best_match_summary(game, now):
    """Try the competition feed when the all-soccer summary lacks current detail."""
    candidates = []
    codes = [game.get('competitionCode')]
    try:
        packet = load_daily_summary(game['id'])
        observation = parse_match_observations(game, packet['summary'])
        candidates.append((packet, observation))
        if observation['state'] in ('in', 'post') and has_player_stats(observation):
            return packet, observation
        codes.insert(0, packet['summary'].get('header', {}).get('league', {}).get('slug'))
    except Exception:
        pass
    if not candidates or game.get('state') == 'in' or parse_time(game['kickoff_time']) <= now:
        code = next((v for v in codes if isinstance(v, str) and
                     re.fullmatch(r'[a-z0-9_]+(?:[.-][a-z0-9_]+)+', v)), None)
        if code:
            try:
                packet = load_daily_summary(game['id'], code)
                candidates.append((packet, parse_match_observations(game, packet['summary'])))
            except Exception:
                pass
    if not candidates:
        raise ValueError('No verified match summary.')
    return max(candidates, key=lambda c: ({'pre':0,'in':1,'post':2}[c[1]['state']],
                                          has_player_stats(c[1]), bool(c[1]['rows'])))


def open_league(code,day):
    st.session_state['board_view']='Single league'
    st.session_state['league_selection']=code
    st.session_state['match_date' if code=='eng.1' else 'extra_date']=day


def render_daily_fixtures():
    st.subheader("Today's matches across competitions")
    now=datetime.now(ET)
    today=now.date()
    chosen=st.date_input('Fixture date',value=today,min_value=today-timedelta(days=1),max_value=today+timedelta(days=7),key='daily_fixture_date')
    if st.button('↻ Refresh today’s fixtures',key='daily_refresh'):
        load_daily.clear();load_daily_summary.clear()
    try:packet=load_daily(chosen.isoformat())
    except Exception:st.warning('Cross-competition fixture feed unavailable. Use Single league to check a competition directly.');return
    if packet['failures']:st.warning('Some fixture requests failed; the list may be incomplete. Refresh or check the competition directly.')
    games=[g for g in packet['games'] if not g.get('finished') and g.get('state')!='post']
    if not games:st.info('No live or upcoming matches returned for this date. Finished matches are hidden.');return
    search=st.text_input('Find today’s team or competition',key='daily_fixture_search')
    visible=[g for g in games if search.casefold() in (g['matchLabel']+' '+g['competitionLabel']).casefold()]
    if not visible:st.info('No matches match this search.');return
    live=[g for g in visible if g['state']=='in']
    upcoming=[g for g in visible if g['state']=='pre' and parse_time(g['kickoff_time'])>now]
    pending=[g for g in visible if g not in live and g not in upcoming]
    for title, group in [('Upcoming matches', upcoming), ('Live matches', live), ('Status unconfirmed', pending)]:
        if not group:continue
        st.subheader(title)
        records=[]
        for g in group:
            record={'Match':g['matchLabel'], 'Competition':g['competitionLabel']}
            if title=='Live matches':
                record['Score']=f"{g['team_h_score']}–{g['team_a_score']}" if g['team_h_score'] is not None and g['team_a_score'] is not None else '—'
                record['Clock']=g['clock']
            else:
                record['Kickoff ET']=parse_time(g['kickoff_time']).astimezone(ET).strftime('%I:%M %p')
                if title=='Status unconfirmed':
                    record['Status']='Kickoff passed · awaiting feed' if parse_time(g['kickoff_time'])<=now else 'Awaiting feed'
            records.append(record)
        st.dataframe(pd.DataFrame(records),hide_index=True,use_container_width=True,height=min(325,36+35*len(records)))
    if live:st.caption('Live games show match activity only. Scoring forecasts are pregame.')
    lookup={str(g['id']):g for g in [*upcoming,*live,*pending]}
    def match_label(key):
        g=lookup[key]
        time='Live' if g['state']=='in' else 'Status unconfirmed' if g in pending else parse_time(g['kickoff_time']).astimezone(ET).strftime('%I:%M %p ET')
        return f"{g['matchLabel']} · {time}"
    selected=st.selectbox('Match details / open league board',list(lookup),format_func=match_label,key='daily_match_detail')
    if not st.checkbox('Load selected match details',key='daily_load_detail'):return
    game=lookup[selected]
    try:
        details,observation=best_match_summary(game,now)
    except Exception:st.warning('Verified match details unavailable. No player activity is being inferred.');return
    league=details['summary'].get('header',{}).get('league',{})
    code=league.get('slug')
    st.write('**'+league.get('name',game['competitionLabel'])+'** · '+game['matchLabel'])
    if code in {'eng.1',*LEAGUES}:
        st.button('Open this league’s board',key='daily_open_league',on_click=open_league,args=(code,chosen))
    else:st.info('This competition does not have a supported scorer board. Match observations are shown below when available.')
    retrieved=parse_time(details['asOf']).astimezone(ET).strftime('%I:%M:%S %p ET')
    if observation['state']=='post':
        st.info('ESPN reports this match has finished.')
        return
    if observation['state']=='in':
        st.caption(f"Live · ESPN clock: {observation['clock']} · Summary retrieved {retrieved}")
    elif game.get('state')=='in':
        st.caption(f"Live on the scoreboard · ESPN clock: {game.get('clock') or 'Not reported'} · Player summary has not updated.")
    elif parse_time(game['kickoff_time'])<=now:
        st.info('Scheduled kickoff has passed, but ESPN has not confirmed live play in the match feeds.')
        st.caption(f'ESPN match summary retrieved {retrieved}.')
    else:
        st.caption(f'Scheduled · ESPN match summary retrieved {retrieved}.')
    if observation['rows'] and (observation['state']=='in' or (game.get('state')!='in' and parse_time(game['kickoff_time'])>now)):
        st.dataframe(pd.DataFrame(observation['rows']).style.format(precision=0,na_rep='—'),hide_index=True,use_container_width=True)
    if not has_player_stats(observation) or observation['state']=='pre':
        if observation['state']=='in' or game.get('state')=='in':
            st.info('ESPN has not supplied live player stats for this match. Some fixtures have a live score or clock without player coverage.')
        elif parse_time(game['kickoff_time'])<=now:
            st.caption('No live player stats from ESPN yet. A scheduled kickoff by itself does not establish live coverage.')
        elif not observation['rows']:
            st.caption('ESPN has not published player details yet.')
