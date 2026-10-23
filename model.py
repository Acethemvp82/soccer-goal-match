"""Soccer Goal Match v1. Formula-compatible port of the original EPL board."""
from __future__ import annotations
import math
from datetime import datetime, timezone, timedelta
from collections import defaultdict

UTC = timezone.utc

def parse_time(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))

def clamp(value, low, high):
    return max(low, min(high, value))

def js_round(value):
    return math.floor(value + 0.5)

def build_board(data, fixtures, now=None):
    now = now or datetime.now(UTC)
    if not isinstance(data.get('elements'), list) or not isinstance(data.get('teams'), list) or not isinstance(fixtures, list):
        raise ValueError('Unexpected official FPL data format')
    teams = {t['id']: t for t in data['teams']}
    played, conceded = defaultdict(int), defaultdict(float)
    for fixture in fixtures:
        if not fixture.get('finished'):
            continue
        for team, goals in [(fixture['team_h'], fixture.get('team_a_score')), (fixture['team_a'], fixture.get('team_h_score'))]:
            if goals is not None:
                played[team] += 1
                conceded[team] += float(goals)
    league_ga = sum(conceded.values()) / sum(played.values()) if sum(played.values()) else 0
    groups = defaultdict(lambda: {'minutes': 0, 'xg': 0, 'goals': 0})
    for player in data['elements']:
        group = groups[player['element_type']]
        group['minutes'] += float(player.get('minutes') or 0)
        # A missing xG field means the feed cannot support this model.
        group['xg'] += float(player['expected_goals'])
        group['goals'] += float(player.get('goals_scored') or 0)
    upcoming = sorted((f for f in fixtures if not f.get('started') and not f.get('finished') and f.get('kickoff_time') and now < parse_time(f['kickoff_time']) < now + timedelta(days=14)), key=lambda f: f['kickoff_time'])
    rows = []
    for fixture in upcoming:
        for team_id in [fixture['team_h'], fixture['team_a']]:
            opponent_id = fixture['team_a'] if team_id == fixture['team_h'] else fixture['team_h']
            team, opponent = teams.get(team_id), teams.get(opponent_id)
            if not team or not opponent:
                continue
            factor = clamp(((conceded[opponent_id] + 5 * league_ga) / (played[opponent_id] + 5)) / league_ga, .65, 1.5) if league_ga else 1
            for player in data['elements']:
                if player['team'] != team_id or player['element_type'] == 1:
                    continue
                minutes = float(player.get('minutes') or 0)
                group = groups[player['element_type']]
                sufficient = minutes > 0 and played[team_id] > 0 and league_ga > 0 and group['minutes'] > 0
                xg, goals = float(player['expected_goals']), int(player.get('goals_scored') or 0)
                prior_xg = group['xg'] / group['minutes'] * 90 if group['minutes'] else 0
                prior_goals = group['goals'] / group['minutes'] * 90 if group['minutes'] else 0
                xg90 = (xg * 90 + 450 * prior_xg) / (minutes + 450)
                goals90 = (goals * 90 + 450 * prior_goals) / (minutes + 450)
                estimated_minutes = clamp(minutes / played[team_id], 0, 90) if sufficient else None
                expected_goals = (.8 * xg90 + .2 * goals90) * estimated_minutes / 90 * factor if sufficient else None
                status = player.get('status', '')
                rows.append(dict(id=player['id'], fixture=fixture['id'], name=' '.join(filter(None, [player.get('first_name'), player.get('second_name')])), short=player['web_name'], team=team['short_name'], teamName=team['name'], opponent=opponent['short_name'], home=team_id == fixture['team_h'], kickoff=fixture['kickoff_time'], position={2: 'DEF', 3: 'MID', 4: 'FWD'}.get(player['element_type'], 'OUT'), minutes=js_round(estimated_minutes) if estimated_minutes is not None else None, seasonMinutes=minutes, goals=goals, xg=xg, xg90=xg / minutes * 90 if minutes else None, adjustment=factor, goalMatch=js_round(clamp(50 + 60 * (factor - 1), 0, 100)) if sufficient else None, rate=xg90 if sufficient else None, probability=1-math.exp(-expected_goals) if expected_goals is not None else None, availability={'a': 'Available', 'd': 'Doubtful', 'i': 'Injured', 's': 'Suspended'}.get(status, 'Unavailable'), available=status == 'a', lineup='Unconfirmed', limited=minutes < 450, news=player.get('news') or '', asOf=now.isoformat()))
    rates = sorted({r['id']: r['rate'] for r in rows if r['rate'] is not None}.values())
    for row in rows:
        row['goalThreat'] = js_round(100 * sum(rate < row['rate'] for rate in rates) / max(1, len(rates)-1)) if row['rate'] is not None else None
    return dict(rows=rows, fixtures=[dict(id=f['id'], home=teams[f['team_h']]['short_name'], away=teams[f['team_a']]['short_name'], kickoff=f['kickoff_time']) for f in upcoming], asOf=now.isoformat(), source='Official Fantasy Premier League')

def scoring_outlook(row):
    if not row['available']:
        return 'Unavailable'
    if row['probability'] is None:
        return 'No estimate'
    if row['limited']:
        return 'Limited data'
    if row['probability'] >= .35:
        return 'Strongest'
    if row['probability'] >= .20:
        return 'Strong'
    if row['probability'] >= .10:
        return 'Moderate'
    return 'Low'

def rank_slate(rows):
    """Rank available players before team/position/search filters."""
    rows = sorted((dict(r) for r in rows), key=lambda r: (-(r['probability'] if r['probability'] is not None else -1), r['name']))
    team_counts = defaultdict(int)
    position_counts = defaultdict(int)
    league_counts = defaultdict(int)
    for row in rows:
        row['overallRank'] = row['teamRank'] = row['positionRank'] = None
        if row['available'] and row['probability'] is not None:
            league = row.get('league', 'eng.1')
            league_counts[league] += 1
            team_key = (league, row['team'], row['fixture'])
            position_key = (league, row['position'])
            position_counts[position_key] += 1
            team_counts[team_key] += 1
            row['overallRank'], row['teamRank'] = league_counts[league], team_counts[team_key]
            row['positionRank'] = position_counts[position_key]
        row['outlook'] = scoring_outlook(row)
    return rows
