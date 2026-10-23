"""Official FPL data access. No paid services or API keys required."""
import json
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen
from model import build_board

BASE_URL = 'https://fantasy.premierleague.com/api/'

def fetch_json(endpoint):
    request = Request(BASE_URL + endpoint, headers={'Accept': 'application/json', 'User-Agent': 'SoccerGoalMatch/1.0'})
    with urlopen(request, timeout=20) as response:
        return json.load(response)

def fetch_board():
    with ThreadPoolExecutor(max_workers=2) as pool:
        bootstrap = pool.submit(fetch_json, 'bootstrap-static/')
        fixtures = pool.submit(fetch_json, 'fixtures/')
        return build_board(bootstrap.result(), fixtures.result())
