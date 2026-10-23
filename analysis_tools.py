"""Pregame enrichment, odds arithmetic and evaluation without outcome leakage."""
from __future__ import annotations
import math
import random
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from model import clamp, js_round, parse_time, rank_slate

VERSION = '2.0'

def normalize_name(name):
    text = unicodedata.normalize('NFKD', name or '')
    return re.sub('[^a-z0-9]', '', ''.join(c for c in text if not unicodedata.combining(c)).lower())

def past_history(history, cutoff):
    # A conservative three-hour completion buffer also excludes same-match outcomes.
    return sorted([h for h in history if h.get('kickoff_time') and parse_time(h['kickoff_time']) + timedelta(hours=3) < cutoff], key=lambda h: h['kickoff_time'])

def minutes_profile(history, lineup='Unconfirmed'):
    """Predict a mixture of starter/substitute minutes, conditional on appearing."""
    if not history:
        return None
    recent = history[-5:]
    season_appearances = [h for h in history if h.get('minutes', 0) > 0]
    appearances = [h for h in recent if h.get('minutes', 0) > 0]
    if not appearances or not season_appearances:
        return None
    starters = [h for h in season_appearances if h.get('starts') == 1]
    bench = [h for h in season_appearances if h.get('starts') == 0]
    recent_starters = [h for h in appearances if h.get('starts') == 1]
    recent_bench = [h for h in appearances if h.get('starts') == 0]
    base_start = len(starters) / len(season_appearances)
    p_start = (len(recent_starters) + 2 * base_start) / (len(appearances) + 2)
    starter_pool = (recent_starters or starters)
    bench_pool = (recent_bench or bench)
    starter_minutes = clamp(sum(h['minutes'] for h in starter_pool)/len(starter_pool), 1, 90) if starter_pool else None
    bench_minutes = clamp(sum(h['minutes'] for h in bench_pool)/len(bench_pool), 1, 90) if bench_pool else None
    # No invented starter/sub minutes when that role has no observed history.
    if lineup == 'Confirmed starter':
        if starter_minutes is None:
            return None
        p_start = 1.0
    elif lineup == 'Confirmed bench':
        if bench_minutes is None:
            return None
        p_start = 0.0
    if starter_minutes is None:
        p_start = 0.0
    if bench_minutes is None:
        p_start = 1.0
    conditional_minutes = p_start * (starter_minutes or 0) + (1-p_start) * (bench_minutes or 0)
    return dict(minutes=conditional_minutes, startShare=p_start, starterMinutes=starter_minutes, benchMinutes=bench_minutes, recentStarts=len(recent_starters), recentGames=len(recent), recentMinutes=sum(h.get('minutes', 0) for h in recent), appearances=len(season_appearances))

def rate_profile(history, prior_xg, prior_goals):
    minutes = sum(h.get('minutes', 0) for h in history)
    if minutes <= 0:
        return None
    xg = sum(float(h['expected_goals']) for h in history)
    goals = sum(h.get('goals_scored', 0) for h in history)
    recent = history[-5:]
    recent_minutes = sum(h.get('minutes', 0) for h in recent)
    xg90 = (xg*90 + 450*prior_xg)/(minutes+450)
    goals90 = (goals*90 + 450*prior_goals)/(minutes+450)
    recent_xg90 = (sum(float(h['expected_goals']) for h in recent)*90 + 450*prior_xg)/(recent_minutes+450)
    recent_goals90 = (sum(h.get('goals_scored', 0) for h in recent)*90 + 450*prior_goals)/(recent_minutes+450)
    # Retain xG-led model, adding a modest recent-five-game contribution.
    rate = .8*(.7*xg90+.3*recent_xg90) + .2*(.7*goals90+.3*recent_goals90)
    return dict(rate=rate, xg90=xg90, recentXg90=recent_xg90, sampleMinutes=minutes)

def mixture_probability(rate, profile, factor, minutes_delta=0):
    def chance(minutes):
        if minutes is None:
            return 0.0
        return 1-math.exp(-rate*clamp(minutes+minutes_delta, 0, 90)/90*factor)
    return profile['startShare']*chance(profile['starterMinutes'])+(1-profile['startShare'])*chance(profile['benchMinutes'])

def position_priors(players, histories=None, cutoff=None):
    groups = defaultdict(lambda: [0.,0.,0.])
    for p in players:
        if histories is None:
            vals = [(float(p.get('minutes') or 0),float(p.get('expected_goals') or 0),float(p.get('goals_scored') or 0))]
        else:
            vals = [(float(h.get('minutes') or 0),float(h['expected_goals']),float(h.get('goals_scored') or 0)) for h in past_history(histories.get(p['id'], []), cutoff)]
        for minutes,xg,goals in vals:
            g=groups[p['element_type']];g[0]+=minutes;g[1]+=xg;g[2]+=goals
    return {k:(v[1]/v[0]*90,v[2]/v[0]*90) for k,v in groups.items() if v[0]>0}

def readiness(row, stale=False):
    if stale:
        return 'Stale data — wait'
    if not row['available']:
        return 'Availability concern'
    if row.get('historyStatus') != 'Loaded':
        return 'History missing — wait'
    if row.get('lineup') == 'Confirmed bench':
        return 'Bench — review rules'
    if row.get('lineup') != 'Confirmed starter':
        return 'Await starting XI'
    if row.get('limited') or row.get('historyGames',0)<3:
        return 'Limited sample'
    if row.get('minutes',0)<60:
        return 'Minutes concern'
    return 'Inputs checked — unvalidated'

def enrich_rows(rows, players, histories, lineup_map, as_of, stale=False):
    priors=position_priors(players)
    positions={p['id']:p['element_type'] for p in players}
    output=[]
    for original in rows:
        r=dict(original);r['modelVersion']=VERSION;r['asOf']=as_of.isoformat();r['historyStatus']='Missing';r['probabilityLow']=r['probabilityHigh']=None
        r['lineup']=lineup_map.get((r['fixture'],r['id']),'Unconfirmed')
        h=histories.get(r['id'])
        r['historyGames']=0
        if h is not None:
            h=past_history(h,as_of);r['historyGames']=len(h)
            profile=minutes_profile(h,r['lineup'])
            prior=priors.get(positions[r['id']])
            rate=rate_profile(h,*prior) if prior else None
            if profile and rate:
                r['historyStatus']='Loaded';r['rate']=rate['rate'];r['minutes']=js_round(profile['minutes']);r['minutesProfile']=profile
                r['recentXg90']=rate['recentXg90'];r['recentStarts']=profile['recentStarts'];r['recentGames']=profile['recentGames'];r['recentMinutes']=profile['recentMinutes'];r['startShare']=profile['startShare']
                r['probability']=mixture_probability(rate['rate'],profile,r['adjustment'])
                r['probabilityLow']=mixture_probability(rate['rate'],profile,r['adjustment'], -15)
                r['probabilityHigh']=mixture_probability(rate['rate'],profile,r['adjustment'], 15)
            else:
                r['historyStatus']='Insufficient history';r['probability']=None;r['minutes']=None
        else:
            # Never quietly keep the old season-average estimate as the upgraded model.
            r['probability']=None;r['minutes']=None
        r['readiness']=readiness(r,stale)
        output.append(r)
    # Preserve the original Goal Threat percentile scale while showing the new goal estimate.
    return rank_slate(output)

def american_to_decimal(odds):
    odds=float(odds)
    if not math.isfinite(odds) or -100 < odds < 100:
        raise ValueError('American odds must be +100 or greater, or -100 or lower.')
    return 1+odds/100 if odds>0 else 1+100/abs(odds)

def compare_odds(probability, odds):
    if probability is None or not 0<=probability<=1:
        raise ValueError('No model estimate is available.')
    decimal=american_to_decimal(odds)
    return dict(decimalOdds=decimal,breakEven=1/decimal,edge=probability-1/decimal,expectedReturn=probability*decimal-1,fairDecimal=1/probability if probability else None)

def walk_forward(players, histories, fixtures, now):
    """Current-season appearance-conditional diagnostic, never a profitability backtest."""
    completed={f['id']:f for f in fixtures if f.get('finished') and f.get('kickoff_time') and parse_time(f['kickoff_time'])+timedelta(hours=3)<now}
    group_cache={};opponent_cache={};records=[]
    for p in players:
        h=sorted(histories.get(p['id'],[]),key=lambda x:x.get('kickoff_time',''))
        for target in h:
            f=completed.get(target.get('fixture'))
            if not f or target.get('minutes',0)<=0:
                continue  # Conditional on appearing: DNP is excluded and disclosed.
            cutoff=parse_time(f['kickoff_time'])
            training=past_history(h,cutoff)
            if len(training)<3:
                continue
            if cutoff not in group_cache:
                group_cache[cutoff]=position_priors(players,histories,cutoff)
                games=[x for x in completed.values() if parse_time(x['kickoff_time'])+timedelta(hours=3)<cutoff]
                gc=defaultdict(float);gp=defaultdict(int)
                for g in games:
                    if g.get('team_h_score') is None or g.get('team_a_score') is None:
                        continue
                    gc[g['team_h']]+=g['team_a_score'];gc[g['team_a']]+=g['team_h_score'];gp[g['team_h']]+=1;gp[g['team_a']]+=1
                league=sum(gc.values())/sum(gp.values()) if sum(gp.values()) else 0
                opponent_cache[cutoff]=(gc,gp,league)
            prior=group_cache[cutoff].get(p['element_type']);profile=minutes_profile(training)
            if not prior or not profile:
                continue
            rates=rate_profile(training,*prior)
            if not rates:
                continue
            gc,gp,league=opponent_cache[cutoff]
            opponent=target['opponent_team']
            factor=clamp(((gc[opponent]+5*league)/(gp[opponent]+5))/league,.65,1.5) if league else 1
            probability=mixture_probability(rates['rate'],profile,factor)
            # Per-position scoring-frequency baseline, using training outcomes only.
            key=(cutoff,p['element_type'],'baseline')
            if key not in group_cache:
                past=[x for player in players if player['element_type']==p['element_type'] for x in past_history(histories.get(player['id'],[]),cutoff) if x.get('minutes',0)>0]
                group_cache[key]=(sum(x.get('goals_scored',0)>0 for x in past)+1)/(len(past)+2)
            records.append(dict(playerId=p['id'],fixture=f['id'],kickoff=f['kickoff_time'],probability=probability,baseline=group_cache[key],scored=int(target.get('goals_scored',0)>0)))
    return records

def evaluation_summary(records):
    if not records:
        return None
    n=len(records)
    summary = dict(observations=n,fixtures=len({r['fixture'] for r in records}),scored=sum(r['scored'] for r in records),meanPrediction=sum(r['probability'] for r in records)/n,actualRate=sum(r['scored'] for r in records)/n,brier=sum((r['probability']-r['scored'])**2 for r in records)/n,baselineBrier=sum((r['baseline']-r['scored'])**2 for r in records)/n,logLoss=-sum(r['scored']*math.log(clamp(r['probability'],1e-6,1-1e-6))+(1-r['scored'])*math.log(1-clamp(r['probability'],1e-6,1-1e-6)) for r in records)/n)
    grouped = defaultdict(lambda: [0., 0])
    for row in records:
        g = grouped[row['fixture']]
        g[0] += (row['baseline']-row['scored'])**2 - (row['probability']-row['scored'])**2
        g[1] += 1
    if len(grouped) >= 10:
        rng = random.Random(77)
        games = list(grouped.values())
        draws = []
        for _ in range(2000):
            sample = rng.choices(games, k=len(games))
            draws.append(sum(x[0] for x in sample)/sum(x[1] for x in sample))
        draws.sort()
        summary['fixtureBootstrap95Low'] = draws[int(.025*len(draws))]
        summary['fixtureBootstrap95High'] = draws[int(.975*len(draws))]
    return summary

def grade_snapshot(frame, histories, fixtures):
    """Grade imported pregame records; no forecast reconstruction from outcomes."""
    import pandas as pd
    required={'id','fixture','asOf','probability','modelVersion'}
    if not required.issubset(frame.columns):
        raise ValueError('Upload a v2 export containing id, fixture, asOf, probability, and modelVersion.')
    if len(frame)>2000:
        raise ValueError('Please upload at most 2,000 rows per file.')
    games={f['id']:f for f in fixtures}
    output=[];seen=set()
    for _,record in frame.iterrows():
        try:
            player_id,fixture_id=int(record['id']),int(record['fixture'])
            capture=parse_time(str(record['asOf']))
            game=games.get(fixture_id)
            if not game:
                raise ValueError('Unknown fixture')
            if capture.tzinfo is None or capture>=parse_time(game['kickoff_time']):
                raise ValueError('Capture must be before kickoff')
            probability=float(record['probability'])
            if not math.isfinite(probability) or not 0<=probability<=1:
                raise ValueError('Invalid probability')
            if str(record['modelVersion']) not in ('2','2.0','3.0-basic'):
                raise ValueError('Unsupported model version')
        except (ValueError,TypeError,OverflowError) as exc:
            raise ValueError(f'Invalid export row: {exc}') from exc
        key=(fixture_id,player_id)
        if key in seen:
            raise ValueError('Duplicate player/fixture rows: use one pregame snapshot per fixture.')
        seen.add(key)
        h=next((h for h in histories.get(player_id,[]) if h.get('fixture')==fixture_id),None)
        status='Pending';scored=None;minutes=None
        if game.get('finished'):
            if h is None:
                status='Result unavailable'
            elif not h.get('minutes',0):
                status='DNP — excluded'
            else:
                status='Scored' if h.get('goals_scored',0)>0 else 'No goal';scored=int(h.get('goals_scored',0)>0);minutes=h['minutes']
        paper_return = None
        offered = None
        if 'americanOdds' in frame.columns and pd.notna(record.get('americanOdds')):
            offered = float(record['americanOdds'])
            decimal = american_to_decimal(offered)
            if record.get('nonappearanceRule') != 'void':
                raise ValueError('Priced records require a verified void-on-nonappearance convention.')
            odds_time = parse_time(str(record.get('oddsRecordedAt', '')))
            if odds_time.tzinfo is None or odds_time >= parse_time(game['kickoff_time']):
                raise ValueError('Odds must be recorded before kickoff.')
            if scored is not None:
                paper_return = decimal - 1 if scored else -1
            elif status == 'DNP — excluded':
                paper_return = 0
        output.append({'Player':record.get('name',str(player_id)),'Fixture':fixture_id,'Probability':probability,'Status':status,'Scored':scored,'Minutes':minutes,'Captured':capture.isoformat(),'Recorded American odds':offered,'Paper return / $1':paper_return})
    return pd.DataFrame(output)
