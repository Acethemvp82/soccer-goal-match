"""Streamlit entrypoint for Ace's EPL anytime goal scorer board."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import html
import json
import gzip
import pandas as pd
import streamlit as st
from data_source import fetch_board, fetch_history, load_histories, fetch_lineups
from analysis_tools import enrich_rows, compare_odds, walk_forward, evaluation_summary, grade_snapshot, VERSION
from league_board import LEAGUES, render_extra, render_combined
from model import parse_time, rank_slate
from match_observations import screen_player
from rankings import prepare_rankings, ranking_controls, order_rankings

ET = ZoneInfo('America/New_York')
ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title='Soccer Goal Match | Ace', page_icon='⚽', layout='wide')
st.markdown('''<style>
.block-container{padding-top:2rem;max-width:1550px}h1{letter-spacing:-1px}h2{font-size:1.4rem!important}.eyebrow{letter-spacing:2px;color:#90efb1;font-size:11px;font-weight:700}.schedule{display:flex;gap:12px;overflow-x:auto;margin:10px 0 22px;padding-bottom:8px}.match{min-width:200px;padding:16px 20px;background:#111e1d;border:1px solid #294137;border-radius:11px}.match b{font-size:18px}.match small{display:block;color:#a3b8af;margin-top:5px}.legend{display:flex;gap:18px;flex-wrap:wrap;color:#b5c7bd;font-size:12px;margin:10px 0 15px}[data-testid="stMetric"]{background:#111e1d;padding:14px 18px;border-top:2px solid #497458;border-radius:8px}[data-testid="stDataFrame"]{border:1px solid #294137;border-radius:10px}
</style>''', unsafe_allow_html=True)
st.markdown('<div class="eyebrow">ACE’S MATCHUP LAB / SOCCER</div>', unsafe_allow_html=True)
st.title('Soccer Goal Match')
st.caption('Find the goal threats. Verify the starting XI. Compare the price.')

@st.cache_data(ttl=300, show_spinner=False)
def load_live_board():
    return fetch_board()

@st.cache_data(ttl=3600, max_entries=1000, show_spinner=False)
def load_player_history(player_id):
    return fetch_history(player_id)

@st.cache_data(ttl=120, show_spinner=False)
def load_match_lineups(fixtures, players, teams):
    return fetch_lineups(fixtures, players, teams)


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

def reset_price():
    st.session_state['american_price'] = ''
    st.session_state['void_rule'] = False
    st.session_state['odds_entered_at'] = None

def record_odds_input():
    st.session_state['odds_entered_at'] = datetime.now(timezone.utc).isoformat()

def show_odds(rows, stale):
    with st.expander('Odds comparison — enter your current sportsbook price', expanded=True):
        options = [r for r in rows if r['probability'] is not None]
        if not options:
            st.info('No upgraded estimates are available for odds comparison.')
            return
        lookup = {str(r.get('league', 'eng.1')) + ':' + str(r['id']) + ':' + str(r['fixture']): r for r in options}
        choice = st.selectbox('Player to price', list(lookup), format_func=lambda key: lookup[key]['short'] + ' · ' + lookup[key]['team'] + ' vs ' + lookup[key]['opponent'], key='price_player', on_change=reset_price)
        player = lookup[choice]
        if st.session_state.get('price_context') != choice:
            reset_price()
            st.session_state['price_context'] = choice
        odds_text = st.text_input('American odds', value='', placeholder='Example: +300 or -110', key='american_price', on_change=record_odds_input)
        void_rule = st.checkbox('I checked that this market voids if the player does not appear', value=False, key='void_rule')
        st.caption('Manual price entry; there is no live sportsbook feed. This estimate is conditional on appearing, so the nonappearance rule matters.')
        if not odds_text.strip():
            return
        try:
            result = compare_odds(player['probability'], float(odds_text))
        except (ValueError, TypeError) as exc:
            st.warning(str(exc))
            return
        a,b,c = st.columns(3)
        a.metric('Book break-even', f'{result["breakEven"]:.1%}')
        b.metric('Model estimate', f'{player["probability"]:.1%}')
        c.metric('Model-only edge', f'{result["edge"]*100:+.1f} pp')
        st.write(f'Model-only expected return per unit staked: **{result["expectedReturn"]:+.2f} units** · Model fair decimal price: **{result["fairDecimal"]:.2f}**' if result['fairDecimal'] else 'Model scoring estimate is zero.')
        low = player.get('probabilityLow')
        if low is not None:
            high = player['probabilityHigh']
            st.caption(f'Minutes scenario range: {low:.1%}–{high:.1%}; lower-minutes edge {100*(low-result["breakEven"]):+.1f} pp. This is not a confidence interval.')
        entered_at = st.session_state.get('odds_entered_at')
        price_stale = not entered_at or datetime.now(timezone.utc)-parse_time(entered_at) > timedelta(minutes=10)
        if entered_at:
            st.caption('Price entered ' + parse_time(entered_at).astimezone(ET).strftime('%I:%M %p ET') + '; check the current sportsbook price again before using it.')
        if void_rule and not price_stale:
            priced = dict(player, modelVersion=player.get('modelVersion', VERSION), americanOdds=float(odds_text), oddsRecordedAt=entered_at, nonappearanceRule='void')
            st.download_button('Save priced pregame record', pd.DataFrame([priced]).to_csv(index=False).encode('utf-8-sig'), file_name='soccer-priced-pregame-record.csv', mime='text/csv')
        if price_stale:
            st.warning('Re-enter the current price: its entry time is missing or more than ten minutes old.')
        elif not void_rule:
            st.warning('Wait: the market nonappearance rule has not been confirmed.')
        elif stale or player.get('readiness') != 'Inputs checked — unvalidated':
            st.warning('Watch only: ' + player.get('readiness', 'Inputs not verified'))
        elif low is not None and low > result['breakEven']:
            st.info('Price clears the model’s lower-minutes scenario. Predictive accuracy and profitability are still unvalidated.')
        else:
            st.info('This price does not clear the lower-minutes scenario. No robust model edge is established.')


def show_evaluation(board, players):
    with st.expander('Model checks and pregame results tracking'):
        st.markdown('**Pregame tracking:** export the board before kickoff and keep that CSV. Upload it here after games to compare the saved estimates with actual scoring outcomes. Download results to preserve them; uploads and session state are not permanent storage.')
        uploaded = st.file_uploader('Upload one v2 pregame board CSV', type=['csv'], key='results_upload')
        if uploaded and board.get('_fixtures'):
            try:
                imported = pd.read_csv(uploaded)
                required = {'id','fixture','asOf','probability','modelVersion'}
                if not required.issubset(imported.columns) or len(imported)>2000:
                    raise ValueError('Use a v2 board export with at most 2,000 rows.')
                ids = sorted({int(x) for x in imported['id']})
                known = {p['id'] for p in players}
                if any(x not in known for x in ids):
                    raise ValueError('This export includes player IDs outside the current source roster.')
                with st.spinner('Loading actual match outcomes…'):
                    histories, failures = load_histories(ids, loader=load_player_history)
                graded = grade_snapshot(imported, histories, board['_fixtures'])
                st.dataframe(graded, hide_index=True, use_container_width=True)
                settled = graded[graded['Scored'].notna()]
                if len(settled):
                    brier = ((settled['Probability']-settled['Scored'])**2).mean()
                    st.write(f'Graded appearances: **{len(settled)}** · Goalscorer rate: **{settled["Scored"].mean():.1%}** · Mean forecast: **{settled["Probability"].mean():.1%}** · Brier score: **{brier:.4f}** (lower is better).')
                if 'Paper return / $1' in graded and graded['Paper return / $1'].notna().any():
                    priced_results = graded[graded['Paper return / $1'].notna() & graded['Scored'].notna()]
                    if len(priced_results):
                        st.write(f'Paper result at manually recorded prices: **{priced_results["Paper return / $1"].sum():+.2f} units** over **{len(priced_results)}** one-unit observations. These are not verified placed wagers or independent historical odds.')
                st.download_button('Download graded results', graded.to_csv(index=False).encode('utf-8-sig'), file_name='soccer-goal-match-results.csv', mime='text/csv')
                st.caption('DNPs are excluded. Capture timestamps are supplied by the CSV, not independently verified. These results do not establish real-world profitability.')
            except (ValueError, KeyError, TypeError) as exc:
                st.warning(str(exc))
        st.divider()
        st.markdown('**Retrospective diagnostic:** rebuild past predictions from earlier match history only, requiring three prior team-game records. Today’s injury flags and confirmed XIs are not backfilled into past predictions. Evaluation is conditional on appearing and uses the current FPL roster/positions, so roster and coverage bias remain. It is not a forward test or an odds/ROI backtest.')
        if players and st.button('Run current-season retrospective check', key='run_diagnostic'):
            ids = sorted(p['id'] for p in players if p['element_type'] != 1 and p.get('minutes',0)>0)
            with st.spinner('Fetching player histories and rebuilding predictions from past-only inputs…'):
                histories, failures = load_histories(ids, loader=load_player_history)
                records = walk_forward(players, histories, board['_fixtures'], datetime.now(timezone.utc))
                st.session_state['diagnostic_report'] = {'summary':evaluation_summary(records), 'records':records, 'failed':len(failures), 'requested':len(ids)}
        report = st.session_state.get('diagnostic_report')
        if not report:
            try:
                report = json.loads((ROOT/'data'/'validation-v2.json').read_text())
                if report.get('version') != VERSION:
                    report = None
            except (OSError, ValueError):
                report = None
        if report and report.get('summary'):
            summary = report['summary']
            st.write(f'Observations: **{summary["observations"]}** across **{summary["fixtures"]}** fixtures · Source histories loaded: **{report["requested"]-report["failed"]}/{report["requested"]}**')
            c1,c2,c3 = st.columns(3)
            c1.metric('Model Brier (lower better)', f'{summary["brier"]:.4f}')
            c2.metric('Past-only position baseline', f'{summary["baselineBrier"]:.4f}')
            c3.metric('Actual / predicted scorer rate', f'{summary["actualRate"]:.1%} / {summary["meanPrediction"]:.1%}')
            if 'fixtureBootstrap95Low' in summary:
                low, high = summary['fixtureBootstrap95Low'], summary['fixtureBootstrap95High']
                st.caption(f'Fixture-resampled 95% interval for Brier improvement over baseline: {low:+.4f} to {high:+.4f}. Positive favors the model; an interval crossing zero leaves the improvement uncertain. This does not address roster bias.')
            if summary['brier'] >= summary['baselineBrier']:
                st.warning('This diagnostic does not beat the simple position baseline on Brier score. Do not treat green ratings or model-only EV as a verified edge.')
            else:
                st.info('The model has a lower Brier score on this diagnostic. Sampling uncertainty, current-roster bias, and absence of historical odds still prevent a betting-readiness claim.')
            if report.get('records'):
                records = pd.DataFrame(report['records'])
                records['Probability band'] = pd.cut(records['probability'], [0,.1,.2,.35,.5,1], include_lowest=True)
                bins = records.groupby('Probability band', observed=True).agg(Count=('scored','size'), Predicted=('probability','mean'), Actual=('scored','mean')).reset_index()
                bins['Probability band'] = bins['Probability band'].astype(str)
                st.dataframe(bins, hide_index=True, use_container_width=True, column_config={'Predicted':st.column_config.NumberColumn(format='%.3f'),'Actual':st.column_config.NumberColumn(format='%.3f')})
            elif report.get('bins'):
                st.dataframe(pd.DataFrame(report['bins']), hide_index=True, use_container_width=True)
            st.caption('Scoring probabilities remain uncalibrated. Outcomes from the same match are correlated. No performance guarantee or minimum profitable sample is implied.')
        elif report:
            st.info('There are not enough usable completed fixtures and prior histories for this diagnostic yet.')


def epl_daily_rows(date):
    board=load_live_board()
    now=datetime.now(timezone.utc)
    games=[f for f in board['_fixtures'] if not f.get('started') and not f.get('finished') and f.get('kickoff_time') and parse_time(f['kickoff_time'])>now and local_day(f['kickoff_time'])==date]
    ids={g['id'] for g in games}
    rows=[r for r in board['rows'] if r['fixture'] in ids]
    players=board['_bootstrap']['elements']
    histories,failures=load_histories(sorted({r['id'] for r in rows if r['seasonMinutes']>0}),loader=load_player_history)
    near=[g for g in games if parse_time(g['kickoff_time'])-now<=timedelta(minutes=90)]
    teams={t['id']:t for t in board['_bootstrap']['teams']}
    lineups=load_match_lineups(near,players,teams)['mapping'] if near else {}
    calculation_time=datetime.now(timezone.utc)
    return [dict(r,league='eng.1',sourceAsOf=board['asOf'],modelBasis='EPL xG-led') for r in enrich_rows([r for r in rows if parse_time(r['kickoff'])>calculation_time],players,histories,lineups,calculation_time)]

@st.fragment(run_every='2m')
def dashboard():
    view=st.radio('Board view',['Single league','Combined daily board'],horizontal=True,key='board_view')
    if view=='Combined daily board':
        render_combined(style_board,show_odds,epl_daily_rows)
        return
    league_names={'eng.1':'English Premier League',**LEAGUES}
    code=st.selectbox('League / competition',list(league_names),format_func=lambda k:league_names[k],key='league_selection')
    st.caption(f'{len(league_names)} source-listed competitions. A listing does not guarantee current fixtures, player coverage or validated scoring estimates.')
    if code!='eng.1':
        render_extra(code,style_board,show_odds)
        return
    if st.button('↻ Refresh data'):
        load_live_board.clear()
        load_match_lineups.clear()
        load_player_history.clear()
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
    slate = [r for r in board['rows'] if r['fixture'] in fixture_ids]
    bootstrap = board.get('_bootstrap')
    raw_fixtures = board.get('_fixtures', [])
    if bootstrap:
        players = bootstrap['elements']
        player_ids = sorted({r['id'] for r in slate if r['seasonMinutes'] > 0})
        with st.spinner('Checking recent match history and starting-XI feeds…'):
            histories, failed = load_histories(player_ids, loader=load_player_history)
            teams = {t['id']: t for t in bootstrap['teams']}
            near_kickoff = [f for f in raw_fixtures if f['id'] in fixture_ids and timedelta(0) < parse_time(f['kickoff_time'])-now <= timedelta(minutes=90)]
            lineup_data = load_match_lineups(near_kickoff, players, teams) if near_kickoff else {'mapping': {}, 'matchedFixtures': 0, 'failures': 0}
        calculation_time = datetime.now(timezone.utc)
        slate = [r for r in slate if parse_time(r['kickoff']) > calculation_time]
        slate = enrich_rows(slate, players, histories, lineup_data['mapping'], calculation_time, stale=bool(warning))
        if failed:
            st.warning(f'Match history unavailable for {len(failed)} players; their upgraded estimates are withheld.')
        if lineup_data['failures']:
            st.warning('Starting-XI feed unavailable for one or more matches. Unverified players remain unconfirmed.')
        checked = sum(r['lineup'] == 'Confirmed starter' for r in slate)
        st.caption(f'{checked} outfield starters confirmed by ESPN. Starting XIs are checked within 90 minutes of kickoff; unmatched players remain unconfirmed.' if checked else 'Starting XIs pending or unmatched. ESPN is checked within 90 minutes of kickoff; every unverified player stays unconfirmed.')
    else:
        players = []
        slate = rank_slate([dict(r, probability=None, minutes=None, readiness='Live history unavailable — wait', historyStatus='Missing', modelVersion=VERSION) for r in slate])
        st.warning('Saved v1 data lacks current player histories. Upgraded estimates require the live FPL feed.')
    st.info('Research model · Scoring estimates are conditional on the player appearing. Colors do not establish betting value. Calibration and profitability remain unproven.')
    slate = [dict(r,inputScreen=screen_player(r,datetime.now(timezone.utc))) for r in slate]
    slate = prepare_rankings(slate)
    ranking_order, ranking_limit = ranking_controls('epl_')
    c1, c2, c3, c4 = st.columns([1, 1, 2, 1.5])
    team = c1.selectbox('Team', ['All teams'] + sorted({r['team'] for r in slate}), key='team_filter')
    position = c2.selectbox('Position', ['All outfield', 'FWD', 'MID', 'DEF'])
    search = c3.text_input('Player search', placeholder='Search a player…')
    available_only = c4.checkbox('Available players only', value=True)
    confirmed_only = st.checkbox('Confirmed starters only', value=False, help='Shows only players matched to a published starting XI; it can be empty before team news.')
    screened_only = st.checkbox('Screened starters only', help='Confirmed starter, available, at least 450 sample minutes and three history records, expected minutes at least 60, and complete input checks. This does not validate the forecast.')
    visible = [r for r in slate if (not available_only or r['available']) and (team == 'All teams' or r['team'] == team) and (position == 'All outfield' or r['position'] == position) and search.casefold() in r['name'].casefold() and (not confirmed_only or r['lineup'] == 'Confirmed starter')]
    if screened_only:visible = [r for r in visible if r['inputScreen']=='Inputs screened — unvalidated']
    visible = order_rankings(visible, ranking_order, ranking_limit)
    m1, m2, m3 = st.columns(3)
    m1.metric('Outfield players', len({r['id'] for r in visible}))
    m2.metric('Strongest candidates', sum(r['outlook'] == 'Strongest' for r in visible))
    m3.metric('Matches', len(selected_fixtures))
    st.markdown('<div class="legend"><span>🟢 Strongest ≥35%</span><span>🟡 Strong 20–34.9%</span><span>🟠 Moderate 10–19.9%</span><span>⚪ Low / limited data</span></div>', unsafe_allow_html=True)
    st.caption('Goal Threat: green 80+ · yellow 60–79 · orange 40–59 · red below 40. Goal Match: green 60+ · yellow 55–59 · gray 45–54 (neutral) · orange 40–44 · red below 40. These rating colors use separate scales from Final Anytime.')
    if not visible:
        st.info('No players match these filters. Try another team, position, or date. Starting XIs may not be published yet.')
        show_evaluation(board, players)
        return
    records = []
    for r in visible:
        records.append({'League rank': r['overallRank'], 'Rank change': r['rankChange'], 'Team rank': r['teamRank'], 'Position rank': r.get('positionRank'), 'Player': r['short'], 'Position': r['position'], 'Team': r['team'], 'Opponent': r['opponent'] + (' (H)' if r['home'] else ' (A)'), 'Goal Threat': r['goalThreat'], 'Goal Match': r['goalMatch'], 'Est. minutes': r['minutes'], 'Final Anytime': r['probability'] * 100 if r['probability'] is not None else None, 'Scoring outlook': r['outlook'], 'Availability': r['availability'], 'Lineup': r['lineup'], 'Checks': r.get('readiness', 'Await checks'), 'Starter/minutes screen':r.get('inputScreen'), 'Recent starts': str(r.get('recentStarts', '—')) + '/' + str(r.get('recentGames', '—'))})
    frame = pd.DataFrame(records)
    event = st.dataframe(style_board(frame), hide_index=True, use_container_width=True, height=590, on_select='rerun', selection_mode='single-row', column_config={
        'League rank': st.column_config.NumberColumn(help='Rank across available players on this date, before search/team/position filters.', format='%d'),
        'Position rank': st.column_config.NumberColumn(help='Rank among players with the same position in this league and date, before filters.', format='%d'),
        'Team rank': st.column_config.NumberColumn(help='Rank within the player’s team for this fixture.', format='%d'),
        'Player': st.column_config.TextColumn(width='medium', help='Select this row to view the player’s scoring inputs below.'),
        'Position': st.column_config.TextColumn(help='FPL classifications: FWD, MID, DEF. These are not precise tactical roles.'),
        'Goal Threat': st.column_config.NumberColumn(help='Percentile of smoothed xG per 90. Green 80+, yellow 60–79, orange 40–59, red below 40. Not a probability.', format='%d'),
        'Goal Match': st.column_config.NumberColumn(help='Opponent concession factor. 50 is neutral. Green 60+, yellow 55–59, gray 45–54, orange 40–44, red below 40.', format='%d'),
        'Est. minutes': st.column_config.NumberColumn(help='Recent starter/substitute mixture conditional on appearing. Confirmed role uses observed minutes in that role. No estimate when history is unavailable.', format='%d'),
        'Final Anytime': st.column_config.NumberColumn(help='Unvalidated scoring chance conditional on appearing; recent-five-game form and starter/substitute minutes mixture. Excludes extra time.', format='%.1f%%'),
        'Lineup': st.column_config.TextColumn(help='Confirmed only when ESPN reports a complete XI for the matched fixture and the player matches unambiguously. Available does not mean starting.')})
    st.caption('Select a player’s row to inspect their scoring inputs. Ranks remain unchanged when filtering.')
    export = pd.DataFrame([dict(r, league='eng.1', matchDate=str(selected_date), sourceAsOf=board['asOf']) for r in visible if r['probability'] is not None]).drop(columns=['rate'], errors='ignore')
    st.download_button('Export pregame board ↓', export.to_csv(index=False).encode('utf-8-sig'), file_name=f'soccer-goal-match-{selected_date}.csv', mime='text/csv', disabled=export.empty)
    st.caption('Pregame exports include calculated forecasts only; rows without an estimate are excluded.')
    show_odds(visible, bool(warning))
    selected = event.selection.rows
    if selected and selected[0] < len(visible):
        player = visible[selected[0]]
        with st.container(border=True):
            st.subheader(player['name'])
            st.caption(f'{player["teamName"]} vs {player["opponent"]} · {player["position"]}')
            columns = st.columns(4)
            for col, label, value in zip(columns, ['Season goals', 'Season xG', 'Season minutes', 'Raw xG / 90'], [str(player['goals']), f'{player["xg"]:.2f}', str(int(player['seasonMinutes'])), f'{player["xg90"]:.2f}' if player['xg90'] is not None else '—']):
                col.metric(label, value)
            st.write(f'Availability: **{player["availability"]}** · Starting XI: **{player["lineup"]}** · Opponent factor: **{player["adjustment"]:.2f}×**')
            st.write(f'Checks: **{player.get("readiness", "Await checks")}** · Recent starts: **{player.get("recentStarts", "—")}/{player.get("recentGames", "—")}**')
            if player.get('probabilityLow') is not None:
                st.caption(f'Minutes sensitivity: {player["probabilityLow"]:.1%}–{player["probabilityHigh"]:.1%}. This varies minutes by ±15; it is not a statistical confidence interval.')
            if player['news']:
                st.write(player['news'])
            if player['limited']:
                st.warning('Limited data: fewer than 450 season minutes. Check the player’s current role and starting status.')
    fetched = parse_time(board['asOf']).astimezone(ET).strftime('%b %d, %Y · %I:%M:%S %p ET')
    st.caption(f'Official Fantasy Premier League · Fetched {fetched} · Board refreshes every 2 minutes while open; player histories cache for one hour.')

    show_evaluation(board, players)
    with st.expander('How to read this board'):
        st.markdown("""**Goal Threat** retains the season smoothed xG percentile. **Goal Match** uses opponent goals conceded, with 50 neutral. Their colors use the separate scales printed above.

**Final Anytime v2** is conditional on appearing. It blends 70% season and 30% recent-five-game scoring rates, with an 80% xG / 20% goals mix and a 450-minute position prior. It combines starter/substitute scoring probabilities using recent roles; a confirmed role uses observed minutes in that role. The opponent adjustment remains capped at 0.65–1.50. Weights are provisional and need validation.

**Lineups:** ESPN match date, home/away teams and kickoff must match FPL. A roster must contain exactly 11 explicit starters. Only unambiguous player-name matches are marked confirmed. Missing or ambiguous names remain unconfirmed. Players below 450 minutes remain limited-data candidates. A confirmed XI can change late; refresh before kickoff.

**Minutes sensitivity** varies the playing-time assumptions by ±15 minutes. It does not capture all uncertainty and is not a confidence interval. `Checks` verifies inputs, not predictive reliability. Injury news is shown separately; historical start frequency is not an injury forecast.

**Odds:** manually enter the current American price and verify the bookmaker's nonappearance rule. Break-even includes the offered price's margin; it is not a de-vigged market forecast. Model edge/EV are unvalidated arithmetic, not established profit or a recommendation. Regulation plus stoppage time only.

**Tracking:** export before kickoff. Imported CSV timestamps are user-supplied and cannot be independently authenticated. DNPs are excluded under an appearance-conditional convention. No odds history means no ROI claim. All forecasts remain unvalidated until sufficiently tested.""")
    st.caption('Sources: https://fantasy.premierleague.com/ and ESPN match rosters · Soccer Goal Match v2 · Streamlit')

dashboard()

