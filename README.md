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

## Board

- Eastern-time match schedule; dates covering the next 14 days.
- Overall and team ranks; team, position, availability, and player filters.
- Color-coded Final Anytime and scoring outlook.
- Goal Threat, Goal Match, estimated minutes, and unconfirmed lineup status.
- Select a row to inspect goals, xG, minutes, and opponent adjustment.
- CSV exports retain underlying inputs, fixture/player IDs, ranks, and capture timestamps.
- Live data caching: five minutes. Active-session refresh: ten minutes.

Official source: https://fantasy.premierleague.com/api/ (bootstrap-static and fixtures endpoints). If a live request fails, the app can display the last successful session fetch or the bundled official-data snapshot for up to 24 hours, with a warning and its original fetch time. After that, it shows no estimates rather than continuing with stale data. The bundled snapshot does not update itself. Live requests remain necessary for continuing operation.

## Model limitations

The model is experimental and unvalidated. Final Anytime estimates use 80% smoothed xG/90 and 20% smoothed goals/90, adjusted for playing-time estimates and opponent goals conceded. See the app's explanation for all weights. All starting XIs are unconfirmed. Minutes are season averages, not role-aware projections. Positions use FPL classifications. There are no dedicated penalty-taker, goalkeeper, shot-count, or odds-based value components, and no historical hit rate or automated results tracker.

`model.py` holds the model independently of Streamlit. `data_source.py` fetches public data. `app.py` contains the board. Python outputs were compared with the original JavaScript model across all 1,190 player/fixture rows in the migration data sample.
