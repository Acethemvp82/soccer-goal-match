"""Source-reported match observations, never in-play scoring probabilities."""
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
