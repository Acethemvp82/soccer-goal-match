"""Free public data, with bounded requests and explicit failure handling."""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen
from datetime import datetime, timezone
from model import build_board
from lineups import match_event, parse_lineups

BASE_URL = 'https://fantasy.premierleague.com/api/'
ESPN_URL = 'https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/'

def fetch_url(url):
    request=Request(url,headers={'Accept':'application/json','User-Agent':'SoccerGoalMatch/2.0'})
    with urlopen(request,timeout=15) as response:
        return json.load(response)

def fetch_json(endpoint):
    return fetch_url(BASE_URL+endpoint)

def fetch_board():
    with ThreadPoolExecutor(max_workers=2) as pool:
        bootstrap=pool.submit(fetch_json,'bootstrap-static/')
        fixtures=pool.submit(fetch_json,'fixtures/')
        data,games=bootstrap.result(),fixtures.result()
    board=build_board(data,games)
    board['_bootstrap']=data
    board['_fixtures']=games
    return board

def fetch_history(player_id):
    data=fetch_json(f'element-summary/{int(player_id)}/')
    if not isinstance(data.get('history'),list):
        raise ValueError('Player history is unavailable')
    for row in data['history']:
        if 'expected_goals' not in row or 'starts' not in row:
            raise ValueError('Player history lacks required fields')
    return data['history']

def load_histories(player_ids,loader=fetch_history):
    histories,failures={},[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks={pool.submit(loader,player_id):player_id for player_id in player_ids}
        for task in as_completed(tasks):
            player_id=tasks[task]
            try:
                histories[player_id]=task.result()
            except Exception:
                failures.append(player_id)
    return histories,failures

def fetch_lineups(fixtures,players,teams):
    mapping={};failures=0;matched=0;checked_at=datetime.now(timezone.utc).isoformat()
    by_date={}
    for fixture in fixtures:
        date=fixture['kickoff_time'][:10].replace('-','')
        by_date.setdefault(date,[]).append(fixture)
    for date,games in by_date.items():
        try:
            events=fetch_url(ESPN_URL+'scoreboard?dates='+date).get('events',[])
        except Exception:
            failures+=len(games);continue
        for fixture in games:
            event=match_event(fixture,teams,events)
            if not event:
                continue
            matched+=1
            try:
                summary=fetch_url(ESPN_URL+'summary?event='+event['id'])
                mapping.update(parse_lineups(fixture,players,summary))
            except Exception:
                failures+=1
    return {'mapping':mapping,'checkedAt':checked_at,'matchedFixtures':matched,'failures':failures}
