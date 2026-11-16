"""Multi-competition browsing and an explicitly separate basic scorer model."""
BUILD_ID = 'goal-threat-first-1'
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import json
import pandas as pd
import streamlit as st
from data_source import fetch_url
from extra_leagues import BASE, LEAGUES, BASIC_VERSION, fetch_schedule, fetch_context, make_board, current_lineups, diagnostic
from model import parse_time
from rankings import prepare_rankings, ranking_controls, order_rankings
from analysis_tools import evaluation_summary, grade_snapshot
from match_observations import parse_match_observations, screen_player
from hammer import annotate_hammers, RULE_LABELS, RULE_TEXT, RULE_VERSION
from simulation_ui import render_simulator

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

def match_selector(fixtures, key, default_all=False):
    """Return an upcoming fixture identity, or None for the full slate."""
    labels = {
        identity: f"{home} vs {away} · {parse_time(kickoff).astimezone(ET).strftime('%a, %b %d · %I:%M %p ET')}"
        for identity, home, away, kickoff in sorted(fixtures, key=lambda f: parse_time(f[3]))
    }
    if not labels:
        return None
    labels[None] = 'All upcoming matches'
    options = list(labels)
    if default_all:
        options = [None, *options[:-1]]
    if key in st.session_state and st.session_state[key] not in labels:
        del st.session_state[key]
    return st.selectbox('Match', options, format_func=labels.__getitem__, key=key)


def board_frame(rows, combined=False):
    records = []
    for r in rows:
        name = ('🔨 ' if r.get('hammer') else '') + r['short']
        if r.get('limited') or r.get('outlook') == 'Limited data':
            name += ' · Limited data'
        record = {'Player': name, 'Team': r['team']}
        if combined:
            record['Competition'] = LEAGUES.get(r.get('league'), 'English Premier League')
        record.update({
            'Goal Threat': r['goalThreat'],
            'Goal Match': r['goalMatch'],
            'Final Anytime': r['probability'] * 100 if r['probability'] is not None else None,
            'Lineup': r['lineup'],
        })
        records.append(record)
    return pd.DataFrame(records)


def render_hammer_summary(rows):
    count = sum(r.get('hammer') == '🔨' for r in rows)
    st.write(f'**{count} of {len(rows)} player rows qualify for 🔨 before player filters.**')
    st.write(RULE_TEXT)
    st.caption(RULE_VERSION + ' · Pass counts are separate checks, not numbers of additional qualifiers.')
    counts = [{'Requirement': label, 'Rows passing': sum(r.get('hammerChecks', {}).get(label, False) for r in rows)}
              for label in RULE_LABELS]
    st.dataframe(pd.DataFrame(counts), hide_index=True, use_container_width=True)


def row_key(row):
    return (row.get('league', 'eng.1'), row['fixture'], row['id'])


def render_rows(rows, style_board, show_odds, key, combined=False, fixture=None,
                stale=False, export_context=None, fetched=None):
    now = datetime.now(timezone.utc)
    rows = [dict(r, inputScreen=screen_player(r, now)) for r in rows if parse_time(r['kickoff']) > now]
    rows = annotate_hammers(prepare_rankings(rows), now)
    if fixture is not None:
        rows = [r for r in rows if (row_key(r)[:2] if combined else r['fixture']) == fixture]

    st.subheader('Anytime scorers')
    with st.expander('Player filters'):
        ranking_order, ranking_limit = ranking_controls(key)
        teams = sorted({r['team'] for r in rows})
        a, b, c = st.columns([1, 1, 2])
        team = a.selectbox('Team', ['All teams'] + teams, key=key+'team')
        position = b.selectbox('Position', ['All outfield', 'FWD', 'MID', 'DEF', 'Unknown'], key=key+'position')
        search = c.text_input('Player search', key=key+'search', placeholder='Search a player…')
        a, b = st.columns(2)
        hammer_only = a.checkbox('🔨 Qualifiers only', key=key+'hammer_only')
        starter = b.checkbox('Confirmed starters only', key=key+'starters')
        screened = a.checkbox('Screened starters only', key=key+'screened',
                              help='Confirmed starter with available and complete inputs, at least 450 sample minutes, three history records and 60 estimated minutes.')
        available = b.checkbox('No injury flag only', value=True, key=key+'availability')

    visible = [r for r in rows
               if (team == 'All teams' or r['team'] == team)
               and (position == 'All outfield' or r['position'] == position)
               and search.casefold() in r['name'].casefold()
               and (not starter or r['lineup'] == 'Confirmed starter')
               and (not available or r['available'])
               and (not hammer_only or r.get('hammer') == '🔨')
               and (not screened or r['inputScreen'] == 'Inputs screened — unvalidated')]
    visible = order_rankings(visible, ranking_order, ranking_limit)
    if combined:
        field = {'Final Anytime': 'probability', 'Goal Threat': 'goalThreat', 'Goal Match': 'goalMatch'}[ranking_order]
        visible.sort(key=lambda r: (r.get(field) is None, -(r.get(field) or 0), r['name']))
    if not visible:
        st.info('No players match this view. Try selecting another match or clearing the player filters.')
        return

    forecasts = sum(r['probability'] is not None for r in visible)
    confirmed = sum(r['lineup'] == 'Confirmed starter' for r in visible)
    hammers = sum(r.get('hammer') == '🔨' for r in visible)
    st.caption(f'{forecasts} forecasts · {confirmed} confirmed starters · {hammers} 🔨')
    frame = board_frame(visible, combined=combined and fixture is None)
    st.dataframe(style_board(frame, [r['outlook'] for r in visible]), hide_index=True,
                 use_container_width=True, height=min(520, 36 + 35 * len(frame)), column_config={
        'Player': st.column_config.TextColumn(help='🔨 marks a qualifier. Open Player details to see the checks.'),
        'Team': st.column_config.TextColumn(width='small'),
        'Goal Match': st.column_config.NumberColumn(format='%d', help='Opponent goals-conceded factor; 50 is neutral.'),
        'Goal Threat': st.column_config.NumberColumn(format='%d', help='Scoring-rate percentile, not a probability.'),
        'Final Anytime': st.column_config.NumberColumn(format='%.1f%%', help='Estimated chance of scoring, conditional on appearing.'),
        'Lineup': st.column_config.TextColumn(help='Confirmed when the player can be matched to the reported lineup.'),
    })

    with st.expander('Player details'):
        tool = st.radio('Details to show', ['Player stats', 'Simulator', 'Odds comparison', 'Color guide & 🔨'],
                        horizontal=True, key=key+'details_tool')
        if tool == 'Simulator':
            render_simulator(visible, key, embedded=True)
        elif tool == 'Odds comparison':
            show_odds(visible, stale)
        elif tool == 'Color guide & 🔨':
            st.markdown(
                '**Goal Threat** · Green 80+ · yellow 60–79 · orange 40–59 · red below 40.  \n'
                '**Goal Match** · Green 60+ · yellow 55–59 · gray 45–54 · orange 40–44 · red below 40.  \n'
                '**Final Anytime** · Green 35%+ · yellow 20–34.9% · orange 10–19.9% · gray otherwise or if data are limited.'
            )
            render_hammer_summary(rows)
        else:
            lookup = {row_key(r): r for r in visible}
            chosen = st.selectbox('Player', list(lookup), format_func=lambda k: (
                f"{lookup[k]['name']} · {lookup[k]['team']} vs {lookup[k]['opponent']}"
                + (f" · {LEAGUES.get(k[0], 'English Premier League')}" if combined else '')
            ), key=key+'detail')
            r = lookup[chosen]
            rnk = lambda field: r.get(field) if r.get(field) is not None else '—'
            st.write(f"**{r['name']}** · {r['teamName']} vs {r['opponent']} · {r['position']} · **{rnk('minutes')} est. minutes**")
            st.write(f"League rank **{rnk('overallRank')}** · Change **{rnk('rankChange')}** · Team rank **{rnk('teamRank')}** · Position rank **{rnk('positionRank')}**")
            st.caption('League ranks use Final Anytime before match and player filters. Changes are tracked in this browser session. Model: '+r.get('modelBasis', 'EPL xG-led')+'.')
            recent = f"{rnk('recentStarts')}/{rnk('recentGames')}"
            inputs = [f"Goals: **{r['goals']}**", f"Sample minutes: **{int(r['seasonMinutes'])}**", f"Recent starts: **{recent}**"]
            if r.get('xg') is not None:
                inputs.append(f"xG: **{r['xg']:.2f}**")
            if r.get('xg90') is not None:
                inputs.append(f"xG / 90: **{r['xg90']:.2f}**")
            if r.get('shots') is not None:
                inputs.append(f"Shots: **{r['shots']}**")
            if r.get('adjustment') is not None:
                inputs.append(f"Opponent factor: **{r['adjustment']:.2f}×**")
            st.write(' · '.join(inputs))
            st.write(f"**{r['lineup']}** · {r.get('availability', 'Availability unknown')} · {r.get('readiness', 'Await checks')}")
            st.caption(f"Starter/minutes screen: {r['inputScreen']} · 🔨 {r['hammerReason']}")
            profile = r.get('minutesProfile') or {}
            if profile:
                st.caption(f"Observed role averages: {profile.get('starterMinutes')} minutes as a starter · {profile.get('benchMinutes')} off the bench.")
            if r.get('news'):
                st.write(r['news'])
            if r.get('probabilityLow') is not None:
                st.caption(f"Minutes sensitivity: {r['probabilityLow']:.1%}–{r['probabilityHigh']:.1%}. This is a scenario range.")
            stamp = fetched or r.get('sourceAsOf')
            if stamp:
                st.caption('Source retrieved '+parse_time(stamp).astimezone(ET).strftime('%b %d · %I:%M %p ET')+'. Board refreshes every two minutes while open.')

        export = [dict(r, **(export_context or {})) for r in visible if r['probability'] is not None]
        export_frame = pd.DataFrame(export)
        if export_context:
            export_frame = export_frame.drop(columns=['rate'], errors='ignore')
        st.download_button('Export pregame board', export_frame.to_csv(index=False).encode('utf-8-sig'),
                           file_name=f"soccer-goal-match-{export_context['matchDate']}.csv" if export_context else 'soccer-multi-league-pregame.csv',
                           mime='text/csv', disabled=not export, key=key+'export')
    st.caption('Scoring estimates assume the player appears and are unvalidated.')


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
    if st.button('↻ Refresh league data',key='refresh_extra'):
        load_schedule.clear();load_pregame_summary.clear();load_roster.clear();load_context.clear();load_observation.clear()
    try:
        schedule=load_schedule(code,datetime.now(ET).date().isoformat())
        now=datetime.now(timezone.utc)
        # Keep live fixtures visible without carrying finished matches onto the board.
        today_et=now.astimezone(ET).date()
        games=[g for g in schedule['games'] if not g['finished'] and parse_time(g['kickoff_time']).astimezone(ET).date()>=today_et-timedelta(days=1)]
        dates=sorted({parse_time(g['kickoff_time']).astimezone(ET).date() for g in games})
        if not dates:
            st.info('No live or upcoming matches were returned. Finished matches are hidden.')
            try:
                context=load_context(code,datetime.now(ET).date().isoformat())
                render_checks(code,context,schedule['games'])
            except Exception:
                st.caption('Historical player data is also unavailable for this competition.')
            return
        if st.session_state.get('extra_date') not in dates:
            st.session_state['extra_date']=next((d for d in dates if d>=today_et),dates[-1])
        date=st.selectbox('Match date',dates,format_func=lambda d:d.strftime('%a, %b %d, %Y'),key='extra_date')
        selected=[g for g in games if parse_time(g['kickoff_time']).astimezone(ET).date()==date]
        upcoming=[g for g in selected if not g['started'] and parse_time(g['kickoff_time'])>now]
        live=[g for g in selected if g.get('state')=='in' or (g['started'] and not g['finished'])]
        fixture=match_selector([(g['id'],g['home'].get('displayName','Home'),g['away'].get('displayName','Away'),g['kickoff_time'])
                                for g in upcoming], 'extra_match')
    except Exception:
        st.warning('The league schedule could not be loaded.')
        return
    try:
        with st.spinner('Loading competition histories, squads and published XIs…'):
            rows,schedule,context,failures,_=slate_data(code,date) if upcoming else ([],schedule,None,[],{})
    except Exception:
        st.warning('Scorer estimates could not be loaded for this league.')
        rows,context,failures=[],None,[]
    if schedule['scheduleFailures'] or failures:
        st.warning('Some schedule, roster or lineup requests failed. Coverage is incomplete.')
    if rows:
        render_rows(rows,style_board,show_odds,'extra_',fixture=fixture)
    else:
        st.info('No upcoming player forecasts for this date.')
    if live:
        st.subheader('Live matches')
        st.caption(' · '.join(f"{g['home'].get('displayName','Home')} vs {g['away'].get('displayName','Away')}" for g in live))
        render_match_observations(code,live,schedule.get('asOf'))
    if context:render_checks(code,context,schedule['games'])
    with st.expander('Basic model details and limits'):
        if context:
            st.caption(f'History: {context["requestedMatches"]-len(context["failedMatches"])} / {context["requestedMatches"]} match packets loaded; {context.get("usableMatches", 0)} with usable player histories; {context["missingEntries"]} incomplete player-stat entries; {context["scheduleErrors"]} team schedules unavailable.')
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
    if rows:
        matches = {}
        for r in rows:
            home, away = (r['team'], r['opponent']) if r['home'] else (r['opponent'], r['team'])
            matches[row_key(r)[:2]] = (f"{LEAGUES.get(r.get('league'), 'English Premier League')} · {home}", away, r['kickoff'])
        fixture = match_selector([(identity, *data) for identity, data in matches.items()], 'combined_match', default_all=True)
        if fixture is None:
            st.caption('League models are not calibrated against each other.')
        render_rows(rows,style_board,show_odds,'combined_',combined=True,fixture=fixture)
    else:
        st.info('No player rows were available for the selected date and competitions.')
    with st.expander('Competition coverage'):
        st.dataframe(pd.DataFrame(coverage),hide_index=True,use_container_width=True)
