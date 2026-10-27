"""Source-reported match observations, never in-play scoring probabilities."""
BUILD_ID = '2026-10-27-price-checks'
import math
from model import parse_time


def number(value):
    try:
        result=float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (TypeError, ValueError):
        return None


def parse_match_observations(game, summary):
    header=summary.get('header',{})
    comps=header.get('competitions',[])
    if str(header.get('id')) != str(game['id']) or len(comps) != 1:
        raise ValueError('Match summary does not match the selected fixture.')
    comp=comps[0]
    sides={c.get('homeAway'):c for c in comp.get('competitors',[])}
    if any(str(sides.get(side,{}).get('team',{}).get('id')) != str(game[key]) for side,key in [('home','team_h'),('away','team_a')]):
        raise ValueError('Match summary team identifiers do not match.')
    state=comp.get('status',{}).get('type',{}).get('state')
    if state not in ('pre','in','post'):
        raise ValueError('Match state is unavailable.')
    rows=[];seen=set()
    for team in summary.get('rosters',[]):
        side=team.get('homeAway')
        if side not in sides or str(team.get('team',{}).get('id')) != str(sides[side]['team']['id']):
            continue
        for entry in team.get('roster',[]):
            athlete=entry.get('athlete',{});pid=str(athlete.get('id') or '')
            if not pid or pid in seen:continue
            seen.add(pid)
            stats={s['name']:number(s.get('value')) for s in entry.get('stats',[]) if 'name' in s}
            if stats.get('redCards',0) and stats['redCards']>0:
                status='Sent off'
            elif entry.get('subbedOut') is True:
                status='Substituted off'
            elif entry.get('starter') is True:
                status='Started' if state=='post' else 'Starter — no exit reported'
            elif entry.get('subbedIn') is True:
                status='Substitute used' if state=='post' else 'Substitute used — no exit reported'
            elif entry.get('starter') is False and entry.get('subbedIn') is False:
                status='Did not play' if state=='post' else 'Bench — no entry reported'
            else:status='Status unavailable'
            rows.append({'Player':athlete.get('displayName',pid),'Team':sides[side]['team'].get('displayName',side),'Player status':status,'Goals':stats.get('totalGoals'),'Shots':stats.get('totalShots'),'Shots on target':stats.get('shotsOnTarget')})
    return {'state':state,'clock':comp.get('status',{}).get('displayClock') or comp.get('status',{}).get('type',{}).get('detail','Unavailable'),'homeScore':sides['home'].get('score'),'awayScore':sides['away'].get('score'),'rows':rows}


def screen_player(row, now):
    """Check inputs and role only; passing is not evidence of betting value."""
    if parse_time(row['kickoff']) <= now:return 'Closed — match started'
    if row.get('probability') is None:return 'No estimate'
    if not row.get('available'):return 'Availability concern'
    if row.get('lineup')=='Confirmed bench':return 'Bench'
    if row.get('lineup')!='Confirmed starter':return 'Await starting XI'
    if row.get('limited') or row.get('historyGames',0)<3:return 'Limited history'
    if row.get('minutes') is None or row['minutes']<60:return 'Minutes concern'
    if row.get('readiness') not in ('Inputs checked — unvalidated','Inputs checked — basic unvalidated'):
        return 'Review data checks'
    return 'Inputs screened — unvalidated'



def priced_record_issue(row, now, entered_at, void_rule, stale=False):
    """Require current pregame inputs before saving a new priced research record."""
    try:
        capture=parse_time(row['asOf'])
        kickoff=parse_time(row['kickoff'])
        if capture.tzinfo is None or kickoff.tzinfo is None:
            return 'Forecast time unavailable — refresh data'
        if now>=kickoff or capture>=kickoff:
            return 'Pregame pricing closed — match started'
        age=(now-capture).total_seconds()
        if age<0 or age>600 or stale:
            return 'Forecast is stale — refresh data'
        price_time=parse_time(entered_at) if entered_at else None
        if price_time is None or price_time.tzinfo is None:
            return 'Re-enter the current price'
        price_age=(now-price_time).total_seconds()
        if price_age<0 or price_age>600 or price_time>=kickoff:
            return 'Re-enter the current price'
    except (KeyError,TypeError,ValueError):
        return 'Forecast or price time unavailable — refresh data'
    if not void_rule:
        return 'Verify the market nonappearance rule'
    screen=screen_player(row,now)
    if screen!='Inputs screened — unvalidated':
        return screen
    return None
