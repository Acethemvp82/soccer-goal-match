"""Fetch a fresh multi-league pregame ranking snapshot without running the UI.

Run from repository root:
    python tools/live_rankings.py
Writes data/live-rankings.json. This is a separate process: it never edits the
Streamlit prediction board, ranking logic or styling.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from extra_leagues import LEAGUES, BASE, fetch_schedule, fetch_context, make_board, current_lineups
from data_source import fetch_url
from model import parse_time
from concurrent.futures import ThreadPoolExecutor, as_completed

ET = ZoneInfo("America/New_York")


def league_rows(code, date, now):
    schedule = fetch_schedule(code, date)
    games = [g for g in schedule["games"] if not g["started"] and
             parse_time(g["kickoff_time"]) > now and
             parse_time(g["kickoff_time"]).astimezone(ET).date().isoformat() == date]
    if not games:
        return []
    def summary(fixture):
        return fetch_url(BASE + code + "/summary?event=" + str(fixture))
    context = fetch_context(code, schedule, summary)
    teams = {g[k] for g in games for k in ("team_h", "team_a")}
    rosters = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(fetch_url, BASE + code + "/teams/" + str(team) +
                            "/roster?season=" + str(schedule["season"])): team for team in teams}
        for job in as_completed(jobs):
            try:
                result = job.result()
                if isinstance(result.get("athletes"), list) and int(result.get("season", {}).get("year", -1)) == schedule["season"]:
                    rosters[jobs[job]] = result
            except Exception:
                pass
    near = [g for g in games if 0 < (parse_time(g["kickoff_time"]) - now).total_seconds() <= 5400]
    summaries = {}
    for g in near:
        try:
            summaries[g["id"]] = summary(g["id"])
        except Exception:
            pass
    rows = make_board(code, games, context, rosters, current_lineups(near, summaries), now)
    return [{k: r.get(k) for k in ("league", "name", "short", "team", "opponent",
             "teamRank", "overallRank", "goalThreat", "goalMatch", "probability",
             "lineup", "readiness", "fixture", "kickoff", "modelBasis")} for r in rows
            if r.get("probability") is not None]


def main():
    now = datetime.now(timezone.utc)
    date = now.astimezone(ET).date().isoformat()
    results, errors = [], {}
    # Only basic-model leagues; EPL requires its distinct xG-led pipeline.
    for code in LEAGUES:
        try:
            results.extend(league_rows(code, date, now))
        except Exception as exc:
            errors[code] = type(exc).__name__
    results.sort(key=lambda r: (r["league"], -(r["probability"] or 0)))
    if not results:
        raise RuntimeError("No verified pregame forecasts returned; refusing to replace snapshot")
    payload = {"asOf": now.isoformat(), "dateET": date,
               "coverage": "Non-EPL basic-model competitions only",
               "note": "Independent refresh; check starting XIs and stale timestamps",
               "errors": errors, "players": results}
    target = ROOT / "data" / "live-rankings.json"
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {len(results)} forecasts to {target}")


if __name__ == "__main__":
    main()
