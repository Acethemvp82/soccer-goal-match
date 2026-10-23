"""Streamlit entrypoint for Ace's EPL anytime goal scorer board."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import html
import json
import gzip
import pandas as pd
import streamlit as st
from data_source import fetch_board
from model import parse_time, rank_slate

ET = ZoneInfo('America/New_York')
ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title='Soccer Goal Match | Ace', page_icon='⚽', layout='wide')
st.markdown('''<style>
.block-container{padding-top:2rem;max-width:1550px}h1{letter-spacing:-1px}h2{font-size:1.4rem!important}.eyebrow{letter-spacing:2px;color:#90efb1;font-size:11px;font-weight:700}.schedule{display:flex;gap:12px;overflow-x:auto;margin:10px 0 22px;padding-bottom:8px}.match{min-width:200px;padding:16px 20px;background:#111e1d;border:1px solid #294137;border-radius:11px}.match b{font-size:18px}.match small{display:block;color:#a3b8af;margin-top:5px}.legend{display:flex;gap:18px;flex-wrap:wrap;color:#b5c7bd;font-size:12px;margin:10px 0 15px}[data-testid="stMetric"]{background:#111e1d;padding:14px 18px;border-top:2px solid #497458;border-radius:8px}[data-testid="stDataFrame"]{border:1px solid #294137;border-radius:10px}
</style>''', unsafe_allow_html=True)
st.markdown('<div class="eyebrow">ACE’S MATCHUP LAB / PREMIER LEAGUE</div>', unsafe_allow_html=True)
st.title('Soccer Goal Match')
st.caption('Find the goal threats. Check the minutes. Read the matchup.')

@st.cache_data(ttl=300, show_spinner=False)
def load_live_board():
    return fetch_board()

def local_day(timestamp):
    return parse_time(timestamp).astimezone(ET).date()

def get_data():
    try:
        board = load_live_board()
        st.session_state['last_successful_board'] = board
        return board, None
    except Exception:
        board = st.session_state.get('last_successful_board')
        if not board:
            try:
                with gzip.open(ROOT / 'data' / 'initial_snapshot.json.gz', 'rt', encoding='utf-8') as snapshot:
                    board = json.load(snapshot)
            except (OSError, ValueError):
                board = None
        if board:
            age = datetime.now(timezone.utc) - parse_time(board['asOf'])
            if timedelta(0) <= age < timedelta(hours=24):
                fetched = parse_time(board['asOf']).astimezone(ET).strftime('%b %d, %Y at %I:%M %p ET')
                return board, f'Live refresh unavailable. Showing a saved official-data snapshot fetched {fetched}. Check current availability and lineups.'
        return None, 'Official FPL data could not be loaded. Refresh to retry. No current estimates are available.'

COLORS = {'Strongest': ('#214d35', '#9cf2b6'), 'Strong': ('#45412a', '#f0dc94'), 'Moderate': ('#493628', '#efb68d')}
NEUTRAL = ('#24352e', '#acbdb4')
WEAK = ('#4b292c', '#f3a8ac')

def rating_colors(value, column):
    if pd.isna(value):
        return NEUTRAL
    if column == 'Goal Threat':
        if value >= 80:
            return COLORS['Strongest']
        if value >= 60:
            return COLORS['Strong']
        if value >= 40:
            return COLORS['Moderate']
        return WEAK
    if value >= 60:
        return COLORS['Strongest']
    if value >= 55:
        return COLORS['Strong']
    if value >= 45:
        return NEUTRAL
    if value >= 40:
        return COLORS['Moderate']
    return WEAK

def style_board(frame):
    def style_row(row):
        styles = []
        for column in frame.columns:
            if column in ('Goal Threat', 'Goal Match'):
                bg, fg = rating_colors(row[column], column)
            elif column in ('Final Anytime', 'Scoring outlook'):
                bg, fg = COLORS.get(row['Scoring outlook'], NEUTRAL)
            else:
                styles.append('')
                continue
            styles.append(f'background-color:{bg};color:{fg};font-weight:700')
        return styles
    return frame.style.apply(style_row, axis=1).format(precision=0, na_rep='—')

@st.fragment(run_every='10m')
def dashboard():
    if st.button('↻ Refresh data'):
        load_live_board.clear()
    with st.spinner('Loading official Premier League data…'):
        board, warning = get_data()
    if warning:
        st.warning(warning)
    if not board:
        return
    now = datetime.now(timezone.utc)
    fixtures = [f for f in board['fixtures'] if parse_time(f['kickoff']) > now]
    dates = sorted({local_day(f['kickoff']) for f in fixtures})
    if not dates:
        st.info('No upcoming fixtures in the next 14 days were returned. Refresh for the latest schedule.')
        return
    if st.session_state.get('match_date') not in dates:
        st.session_state['match_date'] = dates[0]
    st.subheader('Match schedule')
    selected_date = st.selectbox('Match date', dates, format_func=lambda d: d.strftime('%a, %b %d, %Y'), key='match_date')
    selected_fixtures = [f for f in fixtures if local_day(f['kickoff']) == selected_date]
    cards = ''.join(f'<div class="match"><b>{html.escape(f["home"])} <span style="color:#93aaa4">vs</span> {html.escape(f["away"])}</b><small>{parse_time(f["kickoff"]).astimezone(ET).strftime("%a, %b %d · %I:%M %p ET")}</small></div>' for f in selected_fixtures)
    st.markdown(f'<div class="schedule">{cards}</div>', unsafe_allow_html=True)
    fixture_ids = {f['id'] for f in selected_fixtures}
    slate = rank_slate([r for r in board['rows'] if r['fixture'] in fixture_ids])
    st.info('Experimental model · Colors describe scoring outlook, not betting value. Estimates have not been validated. Starting XIs are unconfirmed.')
    st.subheader('Anytime goal scorer board')
    c1, c2, c3, c4 = st.columns([1, 1, 2, 1.5])
    team = c1.selectbox('Team', ['All teams'] + sorted({r['team'] for r in slate}), key='team_filter')
    position = c2.selectbox('Position', ['All outfield', 'FWD', 'MID', 'DEF'])
    search = c3.text_input('Player search', placeholder='Search a player…')
    available_only = c4.checkbox('Available players only', value=True)
    visible = [r for r in slate if (not available_only or r['available']) and (team == 'All teams' or r['team'] == team) and (position == 'All outfield' or r['position'] == position) and search.casefold() in r['name'].casefold()]
    m1, m2, m3 = st.columns(3)
    m1.metric('Outfield players', len({r['id'] for r in visible}))
    m2.metric('Strongest candidates', sum(r['outlook'] == 'Strongest' for r in visible))
    m3.metric('Matches', len(selected_fixtures))
    st.markdown('<div class="legend"><span>🟢 Strongest ≥35%</span><span>🟡 Strong 20–34.9%</span><span>🟠 Moderate 10–19.9%</span><span>⚪ Low / limited data</span></div>', unsafe_allow_html=True)
    st.caption('Goal Threat: green 80+ · yellow 60–79 · orange 40–59 · red below 40. Goal Match: green 60+ · yellow 55–59 · gray 45–54 (neutral) · orange 40–44 · red below 40. These rating colors use separate scales from Final Anytime.')
    if not visible:
        st.info('No players match these filters. Try another team, position, or date.')
        return
    records = []
    for r in visible:
        records.append({'Overall': r['overallRank'], 'Team rank': r['teamRank'], 'Player': r['short'], 'Position': r['position'], 'Team': r['team'], 'Opponent': r['opponent'] + (' (H)' if r['home'] else ' (A)'), 'Goal Threat': r['goalThreat'], 'Goal Match': r['goalMatch'], 'Est. minutes': r['minutes'], 'Final Anytime': r['probability'] * 100 if r['probability'] is not None else None, 'Scoring outlook': r['outlook'], 'Availability': r['availability'], 'Lineup': r['lineup']})
    frame = pd.DataFrame(records)
    event = st.dataframe(style_board(frame), hide_index=True, use_container_width=True, height=590, on_select='rerun', selection_mode='single-row', column_config={
        'Overall': st.column_config.NumberColumn(help='Rank across available players on this date, before search/team/position filters.', format='%d'),
        'Team rank': st.column_config.NumberColumn(help='Rank within the player’s team for this fixture.', format='%d'),
        'Player': st.column_config.TextColumn(width='medium', help='Select this row to view the player’s scoring inputs below.'),
        'Position': st.column_config.TextColumn(help='FPL classifications: FWD, MID, DEF. These are not precise tactical roles.'),
        'Goal Threat': st.column_config.NumberColumn(help='Percentile of smoothed xG per 90. Green 80+, yellow 60–79, orange 40–59, red below 40. Not a probability.', format='%d'),
        'Goal Match': st.column_config.NumberColumn(help='Opponent concession factor. 50 is neutral. Green 60+, yellow 55–59, gray 45–54, orange 40–44, red below 40.', format='%d'),
        'Est. minutes': st.column_config.NumberColumn(help='Season minutes divided by completed league matches for the current team, capped at 90. Not a confirmed starting projection.', format='%d'),
        'Final Anytime': st.column_config.NumberColumn(help='Unvalidated estimated chance of at least one goal in regulation plus stoppage time.', format='%.1f%%'),
        'Lineup': st.column_config.TextColumn(help='This source does not supply confirmed starting XIs here. Available does not mean starting.')})
    st.caption('Select a player’s row to inspect their scoring inputs. Ranks remain unchanged when filtering.')
    export = pd.DataFrame([dict(r, matchDate=str(selected_date)) for r in visible]).drop(columns=['rate'], errors='ignore')
    st.download_button('Export pregame board ↓', export.to_csv(index=False).encode('utf-8-sig'), file_name=f'soccer-goal-match-{selected_date}.csv', mime='text/csv')
    selected = event.selection.rows
    if selected and selected[0] < len(visible):
        player = visible[selected[0]]
        with st.container(border=True):
            st.subheader(player['name'])
            st.caption(f'{player["teamName"]} vs {player["opponent"]} · {player["position"]}')
            columns = st.columns(4)
            for col, label, value in zip(columns, ['Season goals', 'Season xG', 'Season minutes', 'Raw xG / 90'], [str(player['goals']), f'{player["xg"]:.2f}', str(int(player['seasonMinutes'])), f'{player["xg90"]:.2f}' if player['xg90'] is not None else '—']):
                col.metric(label, value)
            st.write(f'Availability: **{player["availability"]}** · Starting XI: **Unconfirmed** · Opponent factor: **{player["adjustment"]:.2f}×**')
            if player['news']:
                st.write(player['news'])
            if player['limited']:
                st.warning('Limited data: fewer than 450 season minutes. Check the player’s current role and starting status.')
    fetched = parse_time(board['asOf']).astimezone(ET).strftime('%b %d, %Y · %I:%M:%S %p ET')
    st.caption(f'Official Fantasy Premier League · Fetched {fetched} · Refreshes every 10 minutes while this session is open.')

    with st.expander('How to read this board'):
        st.markdown('''**Goal Threat (0–100)** is the percentile of a player’s smoothed xG per 90 against outfield players in the upcoming two-week schedule. It is a relative rating, not a scoring probability.

**Goal Match (0–100)** uses the opponent’s goals conceded per game relative to the league average, blended with five league-average games. A rating of 50 is neutral; higher is more favorable.

**Final Anytime** combines 80% smoothed xG/90 and 20% smoothed goals/90, then adjusts for estimated minutes and opponent strength. The result becomes an experimental probability through `1 − exp(−expected goals)`. Player rates use 450 minutes of the position group’s average as a prior. Opponent factors are capped at 0.65–1.50. These weights and thresholds are unvalidated.

**Playing time:** season minutes / completed league games for the current team, capped at 90. Transfers, injury returns, and role changes can make this inaccurate. Availability does not confirm a starting spot. All starting XIs remain unconfirmed. Players below 450 minutes receive a gray “Limited data” outlook.

**Ranks:** calculated for available players across the selected date before team, position, or search filters. Unavailable players have no rank. All outfield squad players may appear; this is not a confirmed starting XI.

**Scope:** pregame regulation plus stoppage time. No dedicated goalkeeper, penalty-taker, odds, or shots component is included. No odds-based betting edge or historical hit rate has been established. Export pregame boards to preserve observations for later evaluation.''')
    st.caption('Source: https://fantasy.premierleague.com/ · Soccer Goal Match v1 · Streamlit')

dashboard()
