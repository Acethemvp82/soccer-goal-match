"""Multi-competition browsing and an explicitly separate basic scorer model."""
BUILD_ID = '2026-10-26-tightening-1'
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import json
import html
import pandas as pd
import streamlit as st
from data_source import fetch_url
from extra_leagues import BASE, LEAGUES, BASIC_VERSION, fetch_schedule, fetch_context, make_board, current_lineups, diagnostic
from model import parse_time
from rankings import prepare_rankings, ranking_controls, order_rankings
from analysis_tools import evaluation_summary, grade_snapshot
from match_observations import parse_match_observations, screen_player

ET=ZoneInfo('America/New_York')
CORE={'ger.1':'German Bundesliga','ger.2':'German 2. Bundesliga','fra.1':'French Ligue 1','ita.1':'Italian Serie A','den.1':'Danish Superliga','aut.1':'Austrian Bundesliga','mex.1':'Mexican Liga MX'}

@st.cache_data(ttl=300,show_spinner=False)
def load_schedule(code,date):return fetch_schedule(code,date)

@st.cache_data(ttl=3600,max_entries=3000,show_spinner=False)
def load_summary(code,fixture):return fetch_url(BASE+code+'/summary?event='+str(fixture))

@st.cache_data(ttl=120,max_entries=300,show_spinner=False)
def load_pregame_summary(code,fixture):return fetch_url(BASE+code+'/summary?event='+str(fixture))

@st.cache_data(ttl=3600,max_entries=250,show_spinner=False)
def load_context(code,date):return fetch_context(code,load_schedule(code,date),load_summary)

@st.cache_data(ttl=3600,max_entries=1200,show_spinner=False)
def load_roster(code,team,season):
    d=fetch_url(BASE+code+'/teams/'+str(team)+'/roster?season='+str(season))
    if not isinstance(d.get('athletes'),list) or int(d.get('season',{}).get('year',-1))!=season:raise ValueError('Current-season roster unavailable')
    return d

def slate_data(code,date):
    today=datetime.now(ET).date().isoformat();schedule=load_schedule(code,today);now=datetime.now(timezone.utc)
    games=[g for g in schedule['games'] if not g['started'] and parse_time(g['kickoff_time'])>now and parse_time(g['kickoff_time']).astimezone(ET).date()==date]
    if not games:return [],schedule,None,[],{}
    context=load_context(code,today)
    ids={g[k] for g in games for k in ('team_h','team_a')};rosters={};failures=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(load_roster,code,team,schedule['season']):team for team in ids}
        for task in as_completed(jobs):
            try:rosters[jobs[task]]=task.result()
            except Exception:failures.append(jobs[task])
    near=[g for g in games if timedelta(0)<parse_time(g['kickoff_time'])-now<=timedelta(minutes=90)]
    summaries={}
    for g in near:
        try:summaries[g['id']]=load_pregame_summary(code,g['id'])
        except Exception:failures.append('lineup:'+str(g['id']))
    lineups=current_lineups(near,summaries)
    rows=make_board(code,games,context,rosters,lineups,datetime.now(timezone.utc))
    return rows,schedule,context,failures,rosters

def board_frame(rows,combined=False):
    records=[]
    for r in rows:
        record={'League':LEAGUES.get(r.get('league'), 'English Premier League'),'League rank':r.get('overallRank'),'Rank change':r.get('rankChange'),'Team rank':r.get('teamRank'),'Position rank':r.get('positionRank'),'Player':r['short'],'Position':r['position'],'Team':r['team'],'Opponent':r['opponent']+(' (H)' if r['home'] else ' (A)'),'Goal Threat':r['goalThreat'],'Goal Match':r['goalMatch'],'Est. minutes':r['minutes'],'Final Anytime':r['probability']*100 if r['probability'] is not None else None,'Scoring outlook':r['outlook'],'Lineup':r['lineup'],'Checks':r['readiness'],'Starter/minutes screen':r.get('inputScreen'),'Model':r.get('modelBasis','EPL xG-led')}
        if not combined:record.pop('League')
        records.append(record)
    return pd.DataFrame(records)

def render_rows(rows,style_board,show_odds,key,combined=False):
    rows=[dict(r,inputScreen=screen_player(r,datetime.now(timezone.utc))) for r in rows]
    rows=prepare_rankings(rows)
    ranking_order,ranking_limit=ranking_controls(key)
    teams=sorted({r['team'] for r in rows});a,b,c=st.columns([1,1,2])
    team=a.selectbox('Team',['All teams']+teams,key=key+'team')
    position=b.selectbox('Position',['All outfield','FWD','MID','DEF','Unknown'],key=key+'position')
    search=c.text_input('Player search',key=key+'search',placeholder='Search a player…')
    starter=st.checkbox('Confirmed starters only',key=key+'starters')
    screened=st.checkbox('Screened starters only',key=key+'screened',help='Confirmed starter, available, at least 450 sample minutes and three history records, expected minutes at least 60, and complete input checks. This does not validate the forecast.')
    available=st.checkbox('No injury flag only',value=True,key=key+'availability')
    visible=[r for r in rows if (team=='All teams' or r['team']==team) and (position=='All outfield' or r['position']==position) and search.casefold() in r['name'].casefold() and (not starter or r['lineup']=='Confirmed starter') and (not available or r['available'])]
    if screened:visible=[r for r in visible if r['inputScreen']=='Inputs screened — unvalidated']
    visible=order_rankings(visible,ranking_order,ranking_limit)
    a,b,c=st.columns(3);a.metric('Outfield players',len({(r.get('league'),r['id']) for r in visible}));b.metric('Calculated forecasts',sum(r['probability'] is not None for r in visible));c.metric('Confirmed starters',sum(r['lineup']=='Confirmed starter' for r in visible))
    st.caption('Goal Threat: green 80+, yellow 60–79, orange 40–59, red below 40. Goal Match: green 60+, yellow 55–59, gray 45–54, orange 40–44, red below 40. Final Anytime colors retain the existing scoring bands; they do not establish betting value.')
    if not visible:
        st.info('No players match these filters. Starting XIs may not be published yet.')
        return
    frame=board_frame(visible,combined)
    st.dataframe(style_board(frame),hide_index=True,use_container_width=True,height=560,column_config={'Final Anytime':st.column_config.NumberColumn(format='%.1f%%',help='Uncalibrated chance conditional on appearing. Different league models are not directly calibrated against each other.'),'Goal Threat':st.column_config.NumberColumn(format='%d',help='Basic model: shot/goal rate percentile among loaded competition history, not an xG percentile. EPL retains its xG-led scale.'),'Goal Match':st.column_config.NumberColumn(format='%d',help='Opponent goals-conceded factor; 50 is neutral.'),'Est. minutes':st.column_config.NumberColumn(format='%d',help='Basic model: derived regulation-equivalent starter/substitute minutes; stoppage-time entrants use a minimum of one minute.')})
    export=[r for r in visible if r['probability'] is not None]
    st.download_button('Export pregame board ↓',pd.DataFrame(export).to_csv(index=False).encode('utf-8-sig'),file_name='soccer-multi-league-pregame.csv',mime='text/csv',disabled=not export,key=key+'export')
    st.caption('Exports include calculated forecasts only. Keep them before kickoff; current player and fixture identifiers include the competition in the export.')
    show_odds(visible,False)
    with st.expander('Player inputs'):
        lookup={str(r.get('league'))+':'+str(r['id'])+':'+str(r['fixture']):r for r in visible}
        chosen=st.selectbox('Player details',list(lookup),format_func=k_to_name(lookup),key=key+'detail')
        r=lookup[chosen]
        st.write(f'**{r["name"]}** · {r["teamName"]} · {r["position"]}')
        st.write(f'Goals in loaded history: **{r["goals"]}** · Shots: **{r.get("shots", "Unavailable")}** · Minutes: **{int(r["seasonMinutes"])}** · xG: **Unavailable**' if r.get('league') != 'eng.1' else f'Season goals: **{r["goals"]}** · Season xG: **{r.get("xg", "Unavailable")}**')
        st.write(f'Lineup: **{r["lineup"]}** · **{r["readiness"]}**')
        st.write(f'Starter/minutes screen: **{r["inputScreen"]}**')
        if r.get('recentMinutes') is not None:
            st.caption(f'Recent window: {r.get("recentGames", 0)} records · {r.get("recentStarts", 0)} starts · {r["recentMinutes"]:.0f} minutes · Shots: {r.get("recentShots", "Unavailable")} · Goals: {r.get("recentGoals", "Unavailable")}. Historical production, not live activity.')
        profile=r.get('minutesProfile') or {}
        if profile:st.caption(f'Observed starter minutes: {profile.get("starterMinutes")} · Observed substitute minutes: {profile.get("benchMinutes")}. These are role averages, not a guarantee of playing time.')
        if r.get('news'):st.write(r['news'])
        if r.get('probabilityLow') is not None:st.caption(f'Minutes sensitivity: {r["probabilityLow"]:.1%}–{r["probabilityHigh"]:.1%}. Not a confidence interval.')

def k_to_name(lookup):return lambda k:lookup[k]['name']+' · '+lookup[k]['team']


def render_match_observations(code,games,schedule_as_of=None):
    with st.expander('Match observations — shots and substitutions'):
        st.caption('Source-reported observations only. No next-scorer or remaining-time probabilities. A trailing team alone does not identify the next scorer. Provider data can lag; verify the match clock and player status.')
        if schedule_as_of:st.caption('Schedule retrieved '+parse_time(schedule_as_of).astimezone(ET).strftime('%b %d · %I:%M:%S %p ET'))
        if not st.checkbox('Load match observations',key='observe_'+code):return
        lookup={str(g['id']):g for g in games}
        if not lookup:st.info('No fixture identifiers available.');return
        selected=st.selectbox('Match to inspect',list(lookup),format_func=lambda k:lookup[k]['home'].get('displayName','Home')+' vs '+lookup[k]['away'].get('displayName','Away'),key='observe_match_'+code)
        game=lookup[selected]
        try:
            packet=load_observation(code,game['id'])
            observed=parse_match_observations(game,packet['summary'])
        except Exception:
            st.warning('Verified match observations unavailable. No live player activity is being inferred.');return
        st.write(f"**{game['home'].get('displayName','Home')} {observed['homeScore'] if observed['homeScore'] is not None else '—'} – {observed['awayScore'] if observed['awayScore'] is not None else '—'} {game['away'].get('displayName','Away')}** · {observed['clock']}")
        st.caption('Summary retrieved '+parse_time(packet['retrievedAt']).astimezone(ET).strftime('%b %d · %I:%M:%S %p ET')+' · 2-minute cache. Retrieval time is not the provider’s last event time. No exit reported does not confirm a player is still on the field.')
        if not observed['rows']:st.info('No player stats were returned. Missing stats are not counted as zero.');return
        st.dataframe(pd.DataFrame(observed['rows']).style.format(precision=0,na_rep='—'),hide_index=True,use_container_width=True)

@st.cache_data(ttl=120,max_entries=100,show_spinner=False)
def load_observation(code,fixture):
    return {'summary':fetch_url(BASE+code+'/summary?event='+str(fixture)),'retrievedAt':datetime.now(timezone.utc).isoformat()}

def render_extra(code,style_board,show_odds):
    st.subheader(LEAGUES[code])
    st.info('Separate basic model: shots and goals, without xG. Player coverage varies by competition. Missing estimates stay blank; EPL validation does not transfer to this model.')
    if st.button('↻ Refresh league data',key='refresh_extra'):
        load_schedule.clear();load_pregame_summary.clear();load_roster.clear();load_context.clear();load_observation.clear()
    try:
        schedule=load_schedule(code,datetime.now(ET).date().isoformat())
        now=datetime.now(timezone.utc)
        # Keep today's live/completed fixtures visible; do not use them as new pregame predictions.
        today_et=now.astimezone(ET).date()
        games=[g for g in schedule['games'] if parse_time(g['kickoff_time']).astimezone(ET).date()>=today_et-timedelta(days=1)]
        dates=sorted({parse_time(g['kickoff_time']).astimezone(ET).date() for g in games})
        if not dates:
            st.info('No fixtures were returned for yesterday, today or the next seven days. This competition may be inactive or lack a current schedule feed.')
            try:
                context=load_context(code,datetime.now(ET).date().isoformat())
                render_checks(code,context,schedule['games'])
            except Exception:
                st.caption('Historical player data is also unavailable for this competition.')
            return
        if st.session_state.get('extra_date') not in dates:
            live_dates=[parse_time(g['kickoff_time']).astimezone(ET).date() for g in games if g['started'] and not g['finished'] and parse_time(g['kickoff_time']).astimezone(ET).date()<=today_et]
            st.session_state['extra_date']=max(live_dates) if live_dates else next((d for d in dates if d>=today_et),dates[-1])
        date=st.selectbox('Match date',dates,format_func=lambda d:d.strftime('%a, %b %d, %Y'),key='extra_date')
        with st.spinner('Loading competition histories, squads and published XIs…'):
            rows,schedule,context,failures,rosters=slate_data(code,date)
    except Exception:
        st.warning('Current player data could not be loaded for this competition. No scoring estimates are being substituted from another league.')
        return
    selected=[g for g in games if parse_time(g['kickoff_time']).astimezone(ET).date()==date]
    cards=''.join('<div class="match"><b>'+html.escape(g['home'].get('displayName',''))+' vs '+html.escape(g['away'].get('displayName',''))+'</b><small>'+('FINAL' if g['finished'] else 'LIVE' if g['started'] else parse_time(g['kickoff_time']).astimezone(ET).strftime('%a %I:%M %p ET'))+'</small></div>' for g in selected)
    if any(g['started'] for g in selected):
        st.info('Live/completed matches remain in the fixture list. The player prediction board is pregame-only; no retrospective probabilities are generated after kickoff. Open Match observations below for source-reported shots and substitution status; these are not in-play forecasts.')
    st.markdown('<div class="schedule">'+cards+'</div>',unsafe_allow_html=True)
    if schedule['scheduleFailures'] or failures:st.warning('Some schedule, roster or lineup requests failed. Coverage is incomplete; unmatched starters remain unconfirmed.')
    if context:
        st.caption(f'History: {context["requestedMatches"]-len(context["failedMatches"])} / {context["requestedMatches"]} match packets loaded; {context.get("usableMatches", 0)} with usable player histories; {context["missingEntries"]} incomplete player-stat entries; {context["scheduleErrors"]} team schedules unavailable. History packets are selected from each team’s latest eight completed matches.')
    render_match_observations(code,selected,schedule['asOf'] if 'asOf' in schedule else None)
    if not rows:st.info('No upcoming player forecasts for this date. Started/completed matches are shown above without generating new pregame estimates.');return
    render_rows(rows,style_board,show_odds,'extra_')
    if context:render_checks(code,context,schedule['games'])
    with st.expander('Basic model details and limits'):
        st.markdown('''Rates combine shots per 90 converted using the loaded competition’s positional goals-per-shot rate (70%) and smoothed individual goals per 90 (30%). Each blends 70% available season-window history with 30% last-five-match history. A 450-minute positional prior tempers small samples. Starter/substitute minutes are mixed conditional on appearing. At least three observed appearances are required. Opponent concessions use available earlier league results.

Minutes are reconstructed from explicit starter, substitution and red-card events, capped at regulation time; missing or ambiguous events yield no usable minute record. Stoppage-time substitutes receive a minimum of one minute. This is not an official minutes feed. No xG, penalty-taker, odds feed or dedicated goalkeeper model is included.

Goal Threat is a percentile within loaded competition history. League ranks are separate. Rates from different models/leagues are not calibrated for direct probability comparison. A positive arithmetic edge is not a validated betting edge. Nonappearance rules must be checked with the bookmaker. Lineups are source-reported and can change late.''')
    st.caption('ESPN public match/squad feeds · Basic model 3.0 · Active board refresh: two minutes; completed-history and roster caches: one hour. Refresh league data forces the current squad/lineup checks.')

def render_checks(code,context,scheduled_games):
    with st.expander('This league’s diagnostic and results tracking'):
        if st.button('Run this league’s past-only diagnostic',key='extra_diagnostic'):
            with st.spinner('Rebuilding forecasts from earlier match records…'):
                records=diagnostic(context)
                st.session_state['basic_report_'+code]={'summary':evaluation_summary(records),'records':records}
        report=st.session_state.get('basic_report_'+code)
        if not report:
            try:report=json.loads((Path(__file__).resolve().parent/'data'/'extra-validation.json').read_text()).get(code)
            except (OSError,ValueError):report=None
        if report and report.get('summary'):
            x=report['summary'];a,b,c=st.columns(3)
            a.metric('Held-out appearances',x['observations']);b.metric('Model Brier',f'{x["brier"]:.4f}');c.metric('Position baseline Brier',f'{x["baselineBrier"]:.4f}')
            st.write(f'Actual scorer rate: **{x["actualRate"]:.1%}** · Mean estimate: **{x["meanPrediction"]:.1%}** · Fixtures: **{x["fixtures"]}**.')
            if x['brier'] >= x['baselineBrier']:
                st.warning('This league’s diagnostic does not beat its simple position baseline. Lower Brier is better; no predictive edge is established.')
            else:
                st.info('Lower Brier than baseline in this sample; sampling and coverage uncertainty still prevent a betting-edge claim.')
            if 'fixtureBootstrap95Low' in x:
                st.caption(f'Fixture-resampled 95% interval for Brier improvement: {x["fixtureBootstrap95Low"]:+.4f} to {x["fixtureBootstrap95High"]:+.4f}. Positive favors the model; crossing zero leaves the apparent improvement uncertain.')
            st.caption('Retrospective and appearance-conditional, within a limited history window. Inputs exclude the target match. Roster/position and coverage bias remain. No historical starting-XI or odds archive is used. This is not a profitability test.')
        else:st.caption('No sufficient league-specific diagnostic has been established yet. The EPL result does not apply here.')
        upload=st.file_uploader('Upload this league’s pregame CSV',type=['csv'],key='extra_results')
        if upload:
            try:
                imported=pd.read_csv(upload)
                if 'league' not in imported or set(imported['league'])!={code}:raise ValueError('Upload an export for this selected competition only.')
                graded=grade_snapshot(imported,context['histories'],list({g['id']:g for g in scheduled_games+context['games']}.values()))
                st.dataframe(graded,hide_index=True,use_container_width=True)
                st.download_button('Download graded results',graded.to_csv(index=False).encode('utf-8-sig'),file_name='soccer-league-results.csv',mime='text/csv',key='extra_results_export')
                st.caption('DNPs excluded; timestamps and manually entered prices are user-supplied. Download to preserve results. Session uploads are not permanent storage.')
            except (ValueError,KeyError,TypeError) as exc:st.warning(str(exc))


def render_combined(style_board,show_odds,epl_loader):
    names={'eng.1':'English Premier League',**LEAGUES}
    st.subheader('Combined daily scorer board')
    st.caption('Browse competition coverage worldwide using the single-league view. This combined view loads up to eight chosen competitions at a time to keep free-feed requests manageable. It is not a complete list of every sportsbook market.')
    selected=st.multiselect('Competitions to combine',list(names),default=['eng.1',*CORE],format_func=lambda k:names[k],max_selections=8,key='combined_competitions')
    date=st.date_input('Slate date',value=datetime.now(ET).date(),min_value=datetime.now(ET).date(),max_value=datetime.now(ET).date()+timedelta(days=7),key='combined_date')
    signature=(tuple(selected),date.isoformat())
    if st.button('Load selected competitions',key='combined_load'):st.session_state['combined_signature']=signature
    if st.session_state.get('combined_signature')!=signature:
        st.info('Choose competitions, then load the combined slate. Initial history loading can take a few minutes.')
        return
    rows=[];coverage=[]
    with st.spinner('Loading selected competitions…'):
        for code in selected:
            try:
                if code=='eng.1':data=epl_loader(date);loaded=data
                else:data=slate_data(code,date);loaded=data[0]
                rows.extend(loaded)
                coverage.append({'Competition':names[code],'Players':len(loaded),'Estimates':sum(r['probability'] is not None for r in loaded),'Status':'Loaded' if loaded else 'No pregame player rows returned'})
            except Exception:coverage.append({'Competition':names[code],'Players':0,'Estimates':0,'Status':'Feed unavailable'})
    st.dataframe(pd.DataFrame(coverage),hide_index=True,use_container_width=True)
    if not rows:st.info('No player rows were available for the selected date and competitions.');return
    st.warning('Different league models are not calibrated against each other. League rank stays within each competition; this combined display is not a global betting-confidence ranking.')
    rows.sort(key=lambda r:(r.get('league','eng.1'),r.get('overallRank') or 99999,r['name']))
    render_rows(rows,style_board,show_odds,'combined_',combined=True)

