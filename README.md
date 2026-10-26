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

## Competition expansion

The app includes a source-listed catalog of 220 soccer competitions captured from ESPN's league registry. A catalog entry is not a claim of active fixtures, player coverage, or validation. The single-competition browser attempts the selected feed; unavailable or inactive competitions display their coverage limitation. The initial six checked additions are Germany's Bundesliga and 2. Bundesliga, France's Ligue 1, Italy's Serie A, Denmark's Superliga, and Austria's Bundesliga.

A combined daily view loads up to eight chosen competitions at a time. It defaults to the EPL plus those six additions. All player rows supplied by the current squads are retained, including rows with insufficient history and blank estimates; filters can hide them deliberately. This does not guarantee every global player or sportsbook market. League ranks stay within each competition, and cross-league probabilities are not jointly calibrated.

The EPL retains its v2 xG-led model. Added competitions use a separate `3.0-basic` model based on shots/goals and derived regulation minutes, with no invented xG. Completed match histories cover the latest eight matches per team. Goals and shots must be explicitly present. Starter/substitution/red-card events must support minutes reconstruction; ambiguous records are omitted. Late stoppage-time substitutes receive a minimum of one minute. Current rosters are loaded separately; published starting XIs require 11 distinct starter IDs and matching fixture/team IDs.

The basic rate is 70% shot rate converted at the loaded competition's position-specific goals-per-shot rate, plus 30% individual smoothed goals/90. It blends 70% available history and 30% last-five-match history, with a 450-minute positional prior. Recent role mixtures and opponent concession factors are applied as in v2. At least three historical appearances are required for a calculated forecast. There is no xG, penalty-taker, or goalkeeper feature. Rates remain uncalibrated and are not betting recommendations.

Historical checks rebuild target-match forecasts from earlier records only. Current position classifications, the finite history window, roster and source coverage bias, and missing historical injury/lineup/odds data limit interpretation. Source packets, usable histories, failed schedules and missing player entries are reported separately. The source-listed catalog snapshot and `extra-validation.json` are deployed with the source; ordinary use does not silently treat every catalog competition as tested.

Data calls are bounded to four parallel HTTP requests per selected league operation. The schedule browser requests eight individual dates, because ESPN soccer scoreboards reject date-range syntax. Team schedules retrieve season histories, then only the selected recent completed matches are loaded. Current squads/history cache for one hour, scoreboards for five minutes, and pregame summaries for two minutes. Combined view can take several minutes on first use. No combined board is loaded until explicitly requested in its controls.

Basic-league exports include a competition identifier and model version. Upload a single competition's CSV in that league's tracker. No authenticated timestamp or immutable forecast archive is provided; download files to preserve them. The combined export can be filtered to a competition before grading. Existing v2 historical results belong to the EPL alone.


## Live pregame rankings

The open board recalculates every two minutes. League, team and position ranks use available players with a calculated Final Anytime estimate, before filters. Sort by Final Anytime, Goal Threat or Goal Match; top-10/top-25 views select the Final Anytime ranks within each league. Combined leagues retain independent ranks.

Rank movement compares changed input snapshots in the current browser session. Widget reruns preserve the last movement; a new session or changed fixture set starts a new comparison. No historical movement database is implied. The board calculation time is separate from source timestamps/cache ages. Automatic reruns respect existing feed caches; the single-league refresh button forces current histories as well as lineups/squads. These are pregame rankings, with started fixtures removed; no in-play scoring model is supplied.


## Coverage and input checks (October 26)

ESPN schedule queries include the previous provider day as well as the next eight days. The single-competition date picker retains yesterday so late fixtures crossing midnight remain inspectable. Liga MX is included in the default combined selection (eight competitions total). Live/final fixture visibility never creates a new pregame forecast.

The optional Screened starters only filter requires a confirmed starter, no availability flag, at least 450 sample minutes and three history records, at least 60 estimated minutes, and complete model input checks. The original probability weights and rank definition are unchanged. Passing this filter is not a validated edge. The basic model now flags low expected minutes consistently.

In the single-competition view, Match observations is an opt-in panel using verified fixture/team identifiers. It displays source-reported goals, shots, shots on target, and substitutions/red cards, with unknown fields left blank and a retrieval timestamp. Its cache is two minutes. No exit reported is not assurance that a player remains on the field. This panel does not estimate next scorers, remaining minutes, or live betting value; the pregame board remains separate.
