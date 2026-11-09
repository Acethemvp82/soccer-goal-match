"""Independent, appearance-conditional scorer simulations using existing model inputs."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import numpy as np
from model import parse_time

SIM_VERSION='soccer-sim-1.0'
RUNS=10_000
SEED=20261109


def finite(value,low,high):
    try:
        result=float(value)
        if isinstance(value,bool) or not math.isfinite(result) or not low<=result<=high:raise ValueError()
        return result
    except (TypeError,ValueError):
        raise ValueError('Missing or invalid scoring inputs') from None


def parameters(row):
    rate=finite(row.get('rate'),0,20)
    factor=finite(row.get('adjustment'),.65,1.5)
    profile=row.get('minutesProfile') or {}
    share=finite(profile.get('startShare'),0,1)
    starter=finite(profile.get('starterMinutes'),1,90) if share>0 else 0.
    bench=finite(profile.get('benchMinutes'),1,90) if share<1 else 0.
    return rate,factor,share,starter,bench


def analytic(row, minutes_delta=0):
    rate,factor,share,starter,bench=parameters(row)
    def chance(minutes):return -math.expm1(-rate*factor*max(0,min(90,minutes+minutes_delta))/90)
    return share*chance(starter)+(1-share)*chance(bench)


def eligibility_issue(row,now):
    try:
        kickoff=parse_time(row['kickoff']);captured=parse_time(row['asOf'])
        if now.tzinfo is None or kickoff.tzinfo is None or captured.tzinfo is None:return 'Missing timezone'
        if kickoff<=now:return 'Match started'
        if not 0<=(now-captured).total_seconds()<=600:return 'Forecast older than 10 minutes or future-dated'
        if row.get('available') is not True:return 'Availability concern'
        if row.get('readiness') not in ('Inputs checked — unvalidated','Inputs checked — basic unvalidated','Await starting XI','Bench — review rules','Limited sample','Minutes concern'):
            return 'Incomplete input checks'
        probability=finite(row.get('probability'),0,1)
        if abs(analytic(row)-probability)>1e-6:return 'Scoring inputs do not reproduce the board estimate'
    except (ValueError,TypeError,KeyError,AttributeError):return 'Missing or invalid scoring inputs'
    return None


def row_identity(row):
    return (str(row.get('league','eng.1')),str(row['fixture']),str(row['id']))


def signature(rows,minutes_delta):
    inputs=[]
    for row in rows:
        inputs.append((row_identity(row),parameters(row),row.get('probability'),row.get('lineup'),row.get('readiness'),row.get('modelVersion'),row.get('overallRank'),row.get('teamRank'),row.get('hammer','')))
    return sha256(json.dumps([SIM_VERSION,SEED,minutes_delta,sorted(inputs)],sort_keys=True).encode()).hexdigest()


def simulate_player(row, now, minutes_delta=0, runs=RUNS, seed=SEED):
    issue=eligibility_issue(row,now)
    if issue:raise ValueError(issue)
    if minutes_delta not in (-15,0,15):raise ValueError('Use -15, 0 or +15 minutes')
    if runs!=RUNS:raise ValueError('This simulator uses 10,000 runs')
    rate,factor,share,starter,bench=parameters(row)
    identity=json.dumps([seed,row_identity(row)])
    rng=np.random.default_rng(int.from_bytes(sha256(identity.encode()).digest()[:16],'big'))
    minutes=np.where(rng.random(runs)<share,starter,bench)
    means=rate*factor*np.clip(minutes+minutes_delta,0,90)/90
    goals=rng.poisson(means)
    scoring_runs=int(np.count_nonzero(goals))
    zero=int(np.count_nonzero(goals==0));one=int(np.count_nonzero(goals==1));multiple=int(np.count_nonzero(goals>=2))
    expected=analytic(row,minutes_delta)
    return dict(league=row.get('league','eng.1'),fixture=row['fixture'],id=row['id'],name=row.get('name',str(row['id'])),team=row.get('team',''),lineup=row.get('lineup','Unconfirmed'),
                overallRank=row.get('overallRank'),teamRank=row.get('teamRank'),hammer=row.get('hammer',''),
                modelProbability=float(row['probability']),scenarioProbability=expected,simulatedProbability=scoring_runs/runs,
                zeroGoals=zero,oneGoal=one,multipleGoals=multiple,scoringRuns=scoring_runs,meanGoals=float(np.mean(goals)),
                samplingMarginPP=196*math.sqrt(expected*(1-expected)/runs),runs=runs,minutesDelta=minutes_delta,seed=seed,
                forecastAsOf=row['asOf'],sourceAsOf=row.get('sourceAsOf'),simulatedAt=now.astimezone(timezone.utc).isoformat(),
                simulationVersion=SIM_VERSION,numpyVersion=np.__version__,modelVersion=row.get('modelVersion'),modelBasis=row.get('modelBasis','EPL xG-led'),
                rate=rate,adjustment=factor,startShare=share,starterMinutes=starter if share>0 else None,benchMinutes=bench if share<1 else None,
                condition='Conditional on appearing; independent player simulations')


def simulate_rows(rows,now,minutes_delta=0):
    identities=[row_identity(r) for r in rows]
    if len(identities)!=len(set(identities)):raise ValueError('Duplicate player/fixture rows')
    return [simulate_player(row,now,minutes_delta) for row in rows]
