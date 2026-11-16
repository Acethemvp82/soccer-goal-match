"""Streamlit entrypoint for Ace's EPL anytime goal scorer board."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import gzip
import pandas as pd
import streamlit as st
from data_source import fetch_board, fetch_history, load_histories, fetch_lineups
from analysis_tools import enrich_rows, compare_odds, walk_forward, evaluation_summary, grade_snapshot, VERSION
# Streamlit can rerun the entrypoint while retaining imported helper modules.
# Reload changed helpers once per process so a source update uses one release.
import importlib
import match_observations as _match_observations
if getattr(_match_observations, 'BUILD_ID', None) != '2026-10-27-price-checks':
    importlib.reload(_match_observations)
import simulation as _simulation
if getattr(_simulation, 'BUILD_ID', None) != '2026-11-09-simulator-2':
    importlib.reload(_simulation)
import simulation_ui as _simulation_ui
if getattr(_simulation_ui, 'BUILD_ID', None) != 'compact-board-1':
    importlib.reload(_simulation_ui)
import extra_leagues as _extra_leagues
if getattr(_extra_leagues, 'BUILD_ID', None) != '2026-11-09-simulator':
    importlib.reload(_extra_leagues)
import rankings as _rankings
if getattr(_rankings, 'BUILD_ID', None) != 'compact-board-1':
    importlib.reload(_rankings)
import league_board as _league_board
if getattr(_league_board, 'BUILD_ID', None) != 'top-five-per-team-1':
    importlib.reload(_league_board)
    _league_board.load_schedule.clear()
    _league_board.load_context.clear()
    _league_board.load_pregame_summary.clear()
from league_board import LEAGUES, render_extra, render_combined, render_rows, match_selector
from model import parse_time, rank_slate
from match_observations import priced_record_issue
import daily_fixtures as _daily_fixtures
import daily_fixtures_ui as _daily_fixtures_ui
if getattr(_daily_fixtures_ui, 'BUILD_ID', None) != 'fanduel-ny-shortlist-1':
    importlib.reload(_daily_fixtures)
    importlib.reload(_daily_fixtures_ui)
    _daily_fixtures_ui.load_daily.clear()
from daily_fixtures_ui import render_daily_fixtures

ET = ZoneInfo('America/New_York')
ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title='Soccer Goal Match | Ace', page_icon='⚽', layout='wide')
st.markdown('''<style>
.block-container{padding-top:2rem;max-width:1400px}h1{letter-spacing:-1px}h2{font-size:1.4rem!important}[data-testid="stDataFrame"]{border:1px solid #303946;border-radius:8px}
[data-testid="stMetric"]{background:#172236;padding:16px;border-radius:12px}
div[data-testid="stCaptionContainer"]{color:#a9b8cc}
</style>''', unsafe_allow_html=True)
st.title('Soccer Goal Match')

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

COLORS = {'Strongest': ('#174c3c', '#f3f6fb'), 'Strong': ('#665220', '#fff0be'), 'Moderate': ('#4a391f', '#ffdec6')}
NEUTRAL = ('#172236', '#eef4fa')
WEAK = ('#563641', '#ffdce5')

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

SOFT_TINTS = {'#174c3c': '#15342d', '#665220': '#383220', '#4a391f': '#30271f',
              '#172236': '#131d2f', '#563641': '#322433'}


def style_board(frame, outlooks):
    def style_row(row):
        styles = []
        for column in frame.columns:
            if column in ('Goal Threat', 'Goal Match'):
                bg, fg = rating_colors(row[column], column)
                styles.append(f'background-color:{SOFT_TINTS[bg]};color:{fg}')
            elif column == 'Final Anytime':
                bg, fg = COLORS.get(outlooks[row.name], NEUTRAL)
                styles.append(f'background-color:{bg};color:{fg};font-weight:700')
            else:
                styles.append('')
        return styles
    return frame.style.apply(style_row, axis=1).format(precision=0, na_rep='—')


def reset_price():
    st.session_state['american_price'] = ''
    st.session_state['void_rule'] = False
    st.session_state['odds_entered_at'] = None

def record_odds_input():
    st.session_state['odds_entered_at'] = datetime.now(timezone.utc).isoformat()

def show_odds(rows, stale):
    pricing_time = datetime.now(timezone.utc)
    options = [r for r in rows if r['probability'] is not None and parse_time(r['kickoff']) > pricing_time]
    if not options:
        st.info('No upcoming estimates are available for pregame odds comparison.')
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
    record_issue = priced_record_issue(player, datetime.now(timezone.utc), entered_at, void_rule, stale)
    if record_issue is None:
        priced = dict(player, modelVersion=player.get('modelVersion', VERSION), americanOdds=float(odds_text), oddsRecordedAt=entered_at, nonappearanceRule='void')
        st.download_button('Save priced pregame record', pd.DataFrame([priced]).to_csv(index=False).encode('utf-8-sig'), file_name='soccer-priced-pregame-record.csv', mime='text/csv')
    st.caption('Saving a priced record requires a screened starter and a forecast and manually entered price no more than ten minutes old. Saved records are for research; screening does not establish betting value.')
    if price_stale:
        st.warning('Re-enter the current price: its entry time is missing or more than ten minutes old.')
    elif not void_rule:
        st.warning('Wait: the market nonappearance rule has not been confirmed.')
    elif record_issue is not None:
        st.warning('Watch only: ' + record_issue)
    elif player.get('readiness') != 'Inputs checked — unvalidated':
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
    view=st.radio('Board view',["Today's matches",'Single league','Combined daily board'],horizontal=True,key='board_view')
    if view=="Today's matches":
        render_daily_fixtures()
        return
    if view=='Combined daily board':
        render_combined(style_board,show_odds,epl_daily_rows)
        return
    league_names={'eng.1':'English Premier League',**LEAGUES}
    code=st.selectbox('League / competition',list(league_names),format_func=lambda k:league_names[k],key='league_selection')
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
        st.info("No upcoming Premier League fixtures. Use Today’s matches to browse other competitions and live games.")
        return
    if st.session_state.get('match_date') not in dates:
        st.session_state['match_date'] = dates[0]
    selected_date = st.selectbox('Match date', dates, format_func=lambda d: d.strftime('%a, %b %d, %Y'), key='match_date')
    selected_fixtures = [f for f in fixtures if local_day(f['kickoff']) == selected_date]
    fixture = match_selector(
        [(f['id'], f['home'], f['away'], f['kickoff']) for f in selected_fixtures], 'epl_match'
    )
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
    else:
        players = []
        slate = rank_slate([dict(r, probability=None, minutes=None, readiness='Live history unavailable — wait', historyStatus='Missing', modelVersion=VERSION) for r in slate])
        st.warning('Saved v1 data lacks current player histories. Upgraded estimates require the live FPL feed.')
    render_rows(slate, style_board, show_odds, 'epl_', fixture=fixture,
                stale=bool(warning), export_context={'league': 'eng.1', 'matchDate': str(selected_date), 'sourceAsOf': board['asOf']},
                fetched=board['asOf'])

    show_evaluation(board, players)
    with st.expander('How to read this board'):
        st.markdown("""**Goal Threat** retains the season smoothed xG percentile. **Goal Match** uses opponent goals conceded, with 50 neutral. Their color scales are explained in Player details.

**Final Anytime v2** is conditional on appearing. It blends 70% season and 30% recent-five-game scoring rates, with an 80% xG / 20% goals mix and a 450-minute position prior. It combines starter/substitute scoring probabilities using recent roles; a confirmed role uses observed minutes in that role. The opponent adjustment remains capped at 0.65–1.50. Weights are provisional and need validation.

**Lineups:** ESPN match date, home/away teams and kickoff must match FPL. A roster must contain exactly 11 explicit starters. Only unambiguous player-name matches are marked confirmed. Missing or ambiguous names remain unconfirmed. Players below 450 minutes remain limited-data candidates. A confirmed XI can change late; refresh before kickoff.

**Minutes sensitivity** varies the playing-time assumptions by ±15 minutes. It does not capture all uncertainty and is not a confidence interval. `Checks` verifies inputs, not predictive reliability. Injury news is shown separately; historical start frequency is not an injury forecast.

**Odds:** manually enter the current American price and verify the bookmaker's nonappearance rule. Break-even includes the offered price's margin; it is not a de-vigged market forecast. Model edge/EV are unvalidated arithmetic, not established profit or a recommendation. Regulation plus stoppage time only.

**Tracking:** export before kickoff. Imported CSV timestamps are user-supplied and cannot be independently authenticated. DNPs are excluded under an appearance-conditional convention. No odds history means no ROI claim. All forecasts remain unvalidated until sufficiently tested.""")

dashboard()



