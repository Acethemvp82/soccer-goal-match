# Soccer Goal Match

Ace's Premier League anytime goal scorer research board, built for Streamlit Community Cloud. Migrated from the original Soccer Goal Match board with the same ratings, model weights, color thresholds, and data source.

## Deploy to Streamlit

The source is in `Acethemvp82/soccer-goal-match`.

1. In Streamlit Community Cloud, choose **Create app → Deploy a public app from GitHub**.
2. Repository: `Acethemvp82/soccer-goal-match`; branch: `main`; main file: `app.py`.
3. Use Python 3.12 in Advanced settings and deploy. No secrets or API keys are needed.

Use your normal repository visibility and Streamlit access preferences. This package contains application source and a timestamped public-data snapshot, without account credentials.

## Run locally

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Board v2

- Eastern-time schedule, overall/team ranks, and color-coded Goal Threat, Goal Match, and Final Anytime.
- Automatic recent match histories for the selected slate, cached for one hour; at most four concurrent history requests.
- Season and recent-five-game xG/goals blend, with separate starter/substitute minutes and a conditional-on-appearance scoring probability.
- ESPN starting-XI checks within 90 minutes of kickoff, refreshed through the active-session refresh. Strict fixture/time/team/name matching; missing or ambiguous matches remain unconfirmed. The starter-only filter can be empty before team news.
- A `Checks` column highlights missing history, uncertain XIs, injury flags, limited samples, and short minutes. It is an input check, not model certification.
- Manual American-odds comparison: break-even, model-only edge/EV, fair decimal odds, and ±15-minute sensitivity. No automatic sportsbook prices, paid APIs, staking advice, or bet placement.
- CSV exports/imports for calculated pregame forecast grading and optional priced records; DNPs excluded. Export results to preserve them. User uploads/session data are not persistent storage. Priced records support paper $1 settlement at manually entered odds, with timestamps and a void-on-DNP convention; these are not verified wagers or independent odds.
- A current-season retrospective diagnostic compares past-only forecasts to a simple past-only position scoring-frequency baseline. Results are conditional on appearing and subject to current-roster/position bias. This is not a profitability or forward-validation backtest.

## Data and refresh

FPL: https://fantasy.premierleague.com/api/ (`bootstrap-static`, `fixtures`, `element-summary/{id}`). ESPN: public EPL scoreboard and match summaries at https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/.

Base FPL cache: five minutes. Player history cache: one hour. ESPN lineup cache: two minutes. Active-session refresh: two minutes. Press **Refresh data** for fresh base and lineup feeds; cached player histories remain cached. Lineups are automatically checked near kickoff. There is no unattended updater when the app is closed.

A bundled v1 snapshot may be displayed for up to 24 hours during a base-feed outage, with a warning. It does not contain the live-history context required by v2, so v2 scoring estimates are withheld in that case. After 24 hours, no stale board is shown.

## Formula and limitations

The formula is provisional: 80% xG and 20% goals, each blending 70% season and 30% last-five-game rates. A 450-minute position-average prior tempers small samples. Starter/substitute minutes are observed historical averages, capped at 90, mixed using recent start frequency conditional on appearing. A confirmed role uses that role's observed minutes; missing role history yields no estimate. Scoring probability is the weighted mixture of `1-exp(-rate * minutes/90 * opponent_factor)` for the two roles. Opponent factors remain capped at 0.65–1.50. The ±15-minute scenario is not a confidence interval.

Final Anytime v2 is **not calibrated or proven profitable**. Historical availability/starting XIs and historical sportsbook odds are not available in the retrospective diagnostic. It uses only earlier histories for rates, minutes, position priors, team concessions, and its baseline, excluding same-day uncompleted fixtures with a three-hour completion buffer. No dedicated penalty-taker, shot-count, or goalkeeper component is included. User-supplied CSV timestamps cannot be independently authenticated. A positive model edge does not establish actual betting value.

## Checks

```bash
python -m unittest discover -s . -p 'test_analysis.py' -v
```

The tests cover odds conversion, starter/substitute roles, future-outcome exclusion, conservative lineup matching, and pregame-result grading. The Streamlit interface is separately smoke-tested with mocked source data before release.
