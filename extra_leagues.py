"""Independent shots/goals model for six ESPN-covered European leagues."""
BUILD_ID = '2026-10-26-tightening-2'
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import math
import re
import json
from pathlib import Path
from data_source import fetch_url
from model import parse_time, clamp, js_round, rank_slate
from analysis_tools import minutes_profile, mixture_probability

LEAGUES={'ger.1':'German Bundesliga','ger.2':'German 2. Bundesliga','fra.1':'French Ligue 1','ita.1':'Italian Serie A','den.1':'Danish Superliga','aut.1':'Austrian Bundesliga'}
try:
    LEAGUES.update(json.loads((Path(__file__).resolve().parent/'data'/'league-catalog.json').read_text()))
except (OSError,ValueError):
    pass
LEAGUES.pop('eng.1',None)
BASE='https://site.api.espn.com/apis/site/v2/sports/soccer/'
BASIC_VERSION='3.0-basic'

def flatten_stats(entry):
    source=entry.get('statistics',{})
    if isinstance(source,list):
        return {s['name']:s.get('value') for s in source if 'name' in s}
    cats=source.get('splits',{}).get('categories',[]) if isinstance(source,dict) else []
    return {s['name']:s.get('value') for cat in cats for s in cat.get('stats',[]) if 'name' in s}

def role(position):
    name=(position.get('name','')+' '+position.get('displayName','')).lower()
    abbr=position.get('abbreviation','')
    if abbr=='G' or 'keeper' in name:return 'GK'
    if abbr=='D' or 'defend' in name or 'back' in name:return 'DEF'
    if abbr=='M' or 'midfield' in name or 'winger' in name:return 'MID'
    if abbr=='F' or 'forward' in name or 'striker' in name:return 'FWD'
    return 'Unknown'

def minute_mark(value):
    # Regulation-equivalent clock: 45+2 remains 45, 90+4 remains 90.
    m=re.fullmatch(r"\s*(\d+)(?:\+\d+)?['’]?\s*",str(value or '').replace("'", '').replace('’', ''))
    return min(90,int(m.group(1))) if m else None

def derived_minutes(entry):
    stats={s['name']:s.get('value') for s in entry.get('stats',[]) if 'name' in s}
    for name in ('minutesPlayed','minutes'):
        if name in stats and stats[name] is not None:
            return clamp(float(stats[name]),0,90)
    starter,sub_in,sub_out=entry.get('starter'),entry.get('subbedIn'),entry.get('subbedOut')
    if not all(isinstance(x,bool) for x in (starter,sub_in,sub_out)) or (starter and sub_in):return None
    substitution=[minute_mark(p.get('clock',{}).get('displayValue')) for p in entry.get('plays',[]) if p.get('substitution')]
    red=[minute_mark(p.get('clock',{}).get('displayValue')) for p in entry.get('plays',[]) if p.get('redCard')]
    if any(m is None for m in substitution+red):return None
    if stats.get('redCards',0) and not red:return None
    if not starter and not sub_in:return 0
    if starter:
        if sub_out and not substitution:return None
        end=min((substitution if sub_out else [])+red+[90])
        return max(1,end)
    if not substitution:return None
    times=sorted(substitution)
    if sub_out and len(times)<2:return None
    start=times[0];end=min(([times[-1]] if sub_out else [])+red+[90])
    return max(1,end-start) if end>=start else None

def normalize_game(event):
    c=event.get('competitions',[{}])[0]
    sides={x.get('homeAway'):x for x in c.get('competitors',[])}
    if not event.get('date') or not all(k in sides for k in ('home','away')):return None
    state=c.get('status',event.get('status',{})).get('type',{}).get('state')
    def score(side):
        val=sides[side].get('score')
        if isinstance(val,dict):val=val.get('value')
        try:return int(val) if state=='post' else None
        except (ValueError,TypeError):return None
    return dict(id=int(event['id']),kickoff_time=event['date'],team_h=int(sides['home']['team']['id']),team_a=int(sides['away']['team']['id']),home=sides['home']['team'],away=sides['away']['team'],finished=state=='post',started=state!='pre',state=state,team_h_score=score('home'),team_a_score=score('away'))

def fetch_schedule(code, date):
    if code not in LEAGUES:raise ValueError('Unsupported league')
    now=datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
    days=[(now+timedelta(days=i)).strftime('%Y%m%d') for i in range(-1,8)]
    replies=[];failures=0
    # Soccer scoreboards accept single dates, not date-range syntax.
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs=[pool.submit(fetch_url,BASE+code+'/scoreboard?dates='+day) for day in days]
        for task in as_completed(jobs):
            try:replies.append(task.result())
            except Exception:failures+=1
    leagues=[league for d in replies for league in d.get('leagues',[])]
    if not leagues:raise ValueError('No current schedule feed is available for this competition')
    year=int(leagues[0].get('season',{}).get('year') or (now.year if now.month>=7 else now.year-1))
    events={e['id']:e for d in replies for e in d.get('events',[]) if e.get('id')}
    games=[]
    for event in events.values():
        game=normalize_game(event)
        if game:games.append(game)
    games.sort(key=lambda g:g['kickoff_time'])
    return {'games':games,'season':year,'asOf':datetime.now(timezone.utc).isoformat(),'league':code,'scheduleFailures':failures}

def history_from_summaries(games,summaries):
    histories=defaultdict(list);players={};missing=0;usable=set()
    game_map={g['id']:g for g in games}
    for game_id,summary in summaries.items():
        game=game_map[game_id]
        # Reject mismatched, nonfinal or extra-time/shootout games.
        header=summary.get('header',{});comps=header.get('competitions',[])
        if str(header.get('id'))!=str(game_id) or not comps or comps[0].get('status',{}).get('type',{}).get('state')!='post':continue
        detail=comps[0].get('status',{}).get('type',{}).get('description','').lower()
        if any(x in detail for x in ('extra','penalt','shootout')):continue
        for team in summary.get('rosters',[]):
            if team.get('homeAway') not in ('home','away'):continue
            team_id=game['team_h'] if team['homeAway']=='home' else game['team_a']
            if str(team.get('team',{}).get('id'))!=str(team_id):continue
            for item in team.get('roster',[]):
                athlete=item.get('athlete',{})
                if not athlete.get('id'):continue
                player_id=int(athlete['id']);position=role(item.get('position',{}))
                if position in ('GK','Unknown'):continue
                minutes=derived_minutes(item)
                stats={s['name']:s.get('value') for s in item.get('stats',[]) if 'name' in s}
                if minutes is None or any(k not in stats or stats[k] is None for k in ('totalGoals','totalShots')):
                    missing+=1;continue
                players[player_id]={'id':player_id,'name':athlete.get('displayName',str(player_id)),'position':position}
                if minutes>0:usable.add(game_id)
                histories[player_id].append(dict(fixture=game_id,kickoff_time=game['kickoff_time'],minutes=minutes,starts=int(item['starter']),goals_scored=int(stats['totalGoals']),shots=float(stats['totalShots']),team=team_id,opponent_team=game['team_a'] if team_id==game['team_h'] else game['team_h']))
    return {'histories':dict(histories),'players':players,'missingEntries':missing,'usableMatches':len(usable)}

def fetch_context(code,schedule,summary_loader):
    now=datetime.now(timezone.utc)
    team_ids={g[side] for g in schedule['games'] for side in ('team_h','team_a')}
    try:
        table=fetch_url('https://site.api.espn.com/apis/v2/sports/soccer/'+code+'/standings?season='+str(schedule['season']))
        def entries(node):
            values=list(node.get('standings',{}).get('entries',[]))
            for child in node.get('children',[]):values.extend(entries(child))
            return values
        team_ids.update(int(t['team']['id']) for t in entries(table))
    except Exception:
        pass
    games={};schedule_errors=0
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(fetch_url,BASE+code+'/teams/'+str(team)+'/schedule?season='+str(schedule['season'])):team for team in team_ids}
        for task in as_completed(jobs):
            try:
                d=task.result()
                if int(d.get('season',{}).get('year',-1))!=schedule['season']:raise ValueError('Season mismatch')
                for event in d.get('events',[]):
                    if int(event.get('season',{}).get('year',schedule['season']))!=schedule['season']:continue
                    g=normalize_game(event)
                    if g and g['finished'] and parse_time(g['kickoff_time'])+timedelta(hours=3)<now:games[g['id']]=g
            except Exception:schedule_errors+=1
    recent=defaultdict(list)
    for g in sorted(games.values(),key=lambda g:g['kickoff_time'],reverse=True):
        recent[g['team_h']].append(g['id']);recent[g['team_a']].append(g['id'])
    ids={i for team in recent.values() for i in team[:8]}
    summaries={};failed=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(summary_loader,code,i):i for i in ids}
        for task in as_completed(jobs):
            try:summaries[jobs[task]]=task.result()
            except Exception:failed.append(jobs[task])
    chosen=[g for g in games.values() if g['id'] in ids]
    data=history_from_summaries(chosen,summaries)
    data.update(asOf=now.isoformat(),failedMatches=failed,requestedMatches=len(ids),scheduleErrors=schedule_errors,games=chosen,teamCount=len(team_ids))
    return data

def cutoff_histories(histories,cutoff):
    return {pid:sorted((h for h in rows if parse_time(h['kickoff_time'])+timedelta(hours=3)<cutoff),key=lambda h:h['kickoff_time']) for pid,rows in histories.items()}

def rate_priors(histories,players):
    pools=defaultdict(lambda:[0.,0.,0.])
    for pid,rows in histories.items():
        if pid not in players:continue
        for h in rows:
            p=pools[players[pid]['position']];p[0]+=h['minutes'];p[1]+=h['goals_scored'];p[2]+=h['shots']
    return {position:{'goals90':p[1]/p[0]*90,'conversion':p[1]/p[2] if p[2] else None} for position,p in pools.items() if p[0]>0}

def basic_rate(history,prior):
    if not prior or prior['conversion'] is None or not history:return None
    def part(rows):
        minutes=sum(h['minutes'] for h in rows);goals=sum(h['goals_scored'] for h in rows);shots=sum(h['shots'] for h in rows)
        if minutes<=0:return None
        goals90=(goals*90+450*prior['goals90'])/(minutes+450)
        shot_rate=(shots*90+450*prior['goals90']/max(prior['conversion'],1e-8))/(minutes+450)
        return .7*shot_rate*prior['conversion']+.3*goals90
    season=part(history);recent=part(history[-5:])
    return .7*season+.3*recent if season is not None and recent is not None else None

def opponent_factors(games,cutoff):
    goals=defaultdict(float);played=defaultdict(int)
    for g in games:
        if not g['finished'] or parse_time(g['kickoff_time'])+timedelta(hours=3)>=cutoff or g.get('team_h_score') is None or g.get('team_a_score') is None:continue
        goals[g['team_h']]+=g['team_a_score'];goals[g['team_a']]+=g['team_h_score'];played[g['team_h']]+=1;played[g['team_a']]+=1
    avg=sum(goals.values())/sum(played.values()) if sum(played.values()) else None
    factors={t:clamp(((goals[t]+5*avg)/(n+5))/avg,.65,1.5) for t,n in played.items()} if avg and avg>0 else {}
    return factors

def current_lineups(games,summaries):
    mapping={}
    for g in games:
        summary=summaries.get(g['id'],{})
        header=summary.get('header',{});comps=header.get('competitions',[])
        if str(header.get('id'))!=str(g['id']) or not comps or comps[0].get('status',{}).get('type',{}).get('state')!='pre':continue
        for t in summary.get('rosters',[]):
            side=t.get('homeAway')
            if side not in ('home','away'):continue
            team_id=g['team_h'] if side=='home' else g['team_a']
            if str(t.get('team',{}).get('id'))!=str(team_id):continue
            roster=t.get('roster',[])
            starting=[p.get('athlete',{}).get('id') for p in roster if p.get('starter') is True]
            if len(starting)!=11 or any(i is None for i in starting) or len(set(starting))!=11:continue
            for p in roster:
                if not p.get('athlete',{}).get('id') or not isinstance(p.get('starter'),bool):continue
                mapping[(g['id'],int(p['athlete']['id']))]='Confirmed starter' if p['starter'] else 'Confirmed bench'
    return mapping

def make_board(code,games,context,rosters,lineups,now=None):
    now=now or datetime.now(timezone.utc)
    histories=cutoff_histories(context['histories'],now);pool=rate_priors(histories,context['players']);factors=opponent_factors(context['games'],now)
    rates={pid:basic_rate(h,pool.get(context['players'][pid]['position'])) for pid,h in histories.items() if pid in context['players']}
    comparison=sorted(v for v in rates.values() if v is not None)
    rows=[]
    for game in games:
        if game['started'] or parse_time(game['kickoff_time'])<=now:continue
        for side in ('home','away'):
            team=game[side];team_id=int(team['id']);opponent=game['away' if side=='home' else 'home'];opp_id=int(opponent['id'])
            roster=rosters.get(team_id,{}).get('athletes',[])
            for p in roster:
                position=role(p.get('position',{}))
                if position=='GK':continue
                pid=int(p['id']);lineup=lineups.get((game['id'],pid),'Unconfirmed');h=histories.get(pid,[]);profile=minutes_profile(h,lineup)
                rate=basic_rate(h,pool.get(position));factor=factors.get(opp_id)
                inj=p.get('injuries',[]);status=p.get('status',{}).get('type','')
                available=not inj and status not in ('injured','suspended','inactive')
                sample=sum(x['minutes'] for x in h);positive=sum(x['minutes']>0 for x in h)
                sufficient=profile is not None and rate is not None and factor is not None and positive>=3
                probability=mixture_probability(rate,profile,factor) if sufficient else None
                threat=js_round(100*sum(x<rate for x in comparison)/max(1,len(comparison)-1)) if rate is not None and comparison else None
                notes='; '.join(str(x.get('shortComment') or x.get('status') or 'Injury flag') for x in inj)
                checks='Await starting XI' if lineup=='Unconfirmed' else 'Bench — review rules' if lineup=='Confirmed bench' else 'Inputs checked — basic unvalidated'
                if not sufficient:checks='History/minutes insufficient'
                elif not available:checks='Availability concern'
                elif sample<450:checks='Limited sample'
                elif profile['minutes']<60:checks='Minutes concern'
                if context['failedMatches'] or context['missingEntries']>0 or context.get('scheduleErrors',0):checks='History incomplete — review'
                rows.append(dict(id=pid,fixture=game['id'],league=code,name=p.get('displayName',str(pid)),short=p.get('displayName',str(pid)),team=team.get('abbreviation',team.get('displayName')),teamName=team.get('displayName'),opponent=opponent.get('abbreviation',opponent.get('displayName')),home=side=='home',position=position,kickoff=game['kickoff_time'],seasonMinutes=sample,goals=sum(x['goals_scored'] for x in h),shots=sum(x['shots'] for x in h),xg=None,xg90=None,goalThreat=threat,goalMatch=js_round(clamp(50+60*(factor-1),0,100)) if factor is not None else None,minutes=js_round(profile['minutes']) if sufficient else None,probability=probability,probabilityLow=mixture_probability(rate,profile,factor,-15) if sufficient else None,probabilityHigh=mixture_probability(rate,profile,factor,15) if sufficient else None,available=available,availability='Flagged' if not available else 'No injury flag',lineup=lineup,limited=sample<450,news=notes,readiness=checks,modelVersion=BASIC_VERSION,modelBasis='Shots/goals; no xG',asOf=now.isoformat(),sourceAsOf=context['asOf'],historyGames=len(h),recentStarts=profile['recentStarts'] if profile else None,recentGames=profile['recentGames'] if profile else None,recentMinutes=profile['recentMinutes'] if profile else None,recentShots=sum(x['shots'] for x in h[-5:]),recentGoals=sum(x['goals_scored'] for x in h[-5:]),minutesProfile=profile))
    return rank_slate(rows)

def diagnostic(context):
    records=[];cache={}
    for pid,history in context['histories'].items():
        player=context['players'].get(pid)
        if not player:continue
        for target in history:
            if target['minutes']<=0:continue
            cutoff=parse_time(target['kickoff_time'])
            if cutoff not in cache:
                h=cutoff_histories(context['histories'],cutoff);priors=rate_priors(h,context['players']);factors=opponent_factors(context['games'],cutoff)
                baseline={}
                for position in ('DEF','MID','FWD'):
                    past=[v for i,values in h.items() if context['players'].get(i,{}).get('position')==position for v in values if v['minutes']>0]
                    baseline[position]=(sum(v['goals_scored']>0 for v in past)+1)/(len(past)+2)
                cache[cutoff]=(h,priors,factors,baseline)
            h,priors,factors,baseline=cache[cutoff];past=h.get(pid,[])
            if sum(x['minutes']>0 for x in past)<3:continue
            profile=minutes_profile(past);rate=basic_rate(past,priors.get(player['position']));factor=factors.get(target['opponent_team'])
            if profile is None or rate is None or factor is None:continue
            records.append(dict(fixture=target['fixture'],playerId=pid,kickoff=target['kickoff_time'],probability=mixture_probability(rate,profile,factor),baseline=baseline[player['position']],scored=int(target['goals_scored']>0)))
    return records

