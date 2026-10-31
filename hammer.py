"""Transparent pregame research marker; never an odds-value or live-bet signal."""
from datetime import timezone
import math
from model import parse_time
from match_observations import screen_player

RULE_VERSION = 'soccer-hammer-1.0'
RULE_LABELS = (
    'Current pregame forecast (≤10 minutes)',
    'Confirmed starter / minutes / history checks',
    'Team rank 1–3',
    'Goal Threat 80+',
    'Goal Match 55+',
    'Final Anytime 20%+',
)
RULE_TEXT = ('All six checks are required: a current pregame forecast (calculated within 10 minutes); '
             'the existing starter/minutes screen (confirmed starter, available, at least 450 sample minutes '
             'and three history records, expected minutes at least 60, complete input checks); '
             'team rank 1–3; Goal Threat ≥80; Goal Match ≥55; Final Anytime ≥20%. '
             'Ranks are within each league and the player’s team/fixture, before filters. '
             'Thresholds are provisional research rules. The marker is not a guarantee, validated edge, '
             'or live next-scorer prediction. No sportsbook price is used.')


def in_range(value, low, high):
    try:
        value=float(value)
        return math.isfinite(value) and low <= value <= high
    except (TypeError,ValueError):
        return False


def evaluate_hammer(row, now):
    current=False
    try:
        capture=parse_time(row['asOf']);kickoff=parse_time(row['kickoff'])
        current=(capture.tzinfo is not None and kickoff.tzinfo is not None and now.tzinfo is not None
                 and capture <= now < kickoff and 0 <= (now-capture).total_seconds() <= 600)
    except (KeyError,TypeError,ValueError,AttributeError):
        pass
    try:
        screened=(screen_player(row,now)=='Inputs screened — unvalidated'
                  and in_range(row.get('seasonMinutes'),450,float('inf'))
                  and in_range(row.get('historyGames'),3,float('inf'))
                  and in_range(row.get('minutes'),60,90))
    except (KeyError,TypeError,ValueError,AttributeError):
        screened=False
    checks=dict(zip(RULE_LABELS,[current,screened,in_range(row.get('teamRank'),1,3),
                                in_range(row.get('goalThreat'),80,100),
                                in_range(row.get('goalMatch'),55,100),
                                in_range(row.get('probability'),.20,1)]))
    failed=[name for name,passes in checks.items() if not passes]
    return dict(hammer='🔨' if not failed else '',hammerRuleVersion=RULE_VERSION,
                hammerChecks=checks,hammerReason='All requirements met' if not failed else '; '.join(failed),
                hammerEvaluatedAt=now.astimezone(timezone.utc).isoformat())


def annotate_hammers(rows, now):
    return [dict(row,**evaluate_hammer(row,now)) for row in rows]
