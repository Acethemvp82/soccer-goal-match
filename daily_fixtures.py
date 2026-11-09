"""Cross-competition fixture discovery, separate from pregame player forecasts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from data_source import fetch_url
from extra_leagues import BASE, normalize_game
from model import parse_time

ET=ZoneInfo('America/New_York')


def normalize_daily_event(event):
    try:
        game=normalize_game(event)
        if not game:return None
        comp=event['competitions'][0]
        status=comp.get('status',event.get('status',{}))
        sides={x.get('homeAway'):x for x in comp.get('competitors',[])}
        state=status.get('type',{}).get('state')
        def score(side):
            value=sides[side].get('score')
            if isinstance(value,dict):value=value.get('value')
            try:return int(value) if state in ('in','post') and value is not None else None
            except (TypeError,ValueError):return None
        game.update(competitionLabel=comp.get('altGameNote') or event.get('season',{}).get('slug') or 'Competition not supplied',
                    matchLabel=game['home'].get('displayName','Home')+' vs '+game['away'].get('displayName','Away'),
                    clock=status.get('displayClock') or status.get('type',{}).get('detail',''),
                    state=state,team_h_score=score('home'),team_a_score=score('away'))
        return game
    except (KeyError,TypeError,ValueError,IndexError):return None


def select_daily_events(packets,selected_date):
    matches={}
    for packet in packets:
        for event in packet.get('events',[]):
            game=normalize_daily_event(event)
            if game and parse_time(game['kickoff_time']).astimezone(ET).date()==selected_date:matches[game['id']]=game
    return sorted(matches.values(),key=lambda g:(g['kickoff_time'],g['id']))


def fetch_daily_fixtures(date_string,loader=fetch_url):
    chosen=date.fromisoformat(date_string)
    # Neighboring provider dates retain fixtures around the ET/UTC boundary.
    days=[(chosen+timedelta(days=delta)).strftime('%Y%m%d') for delta in (-1,1,0)]
    def fetch(day):
        try:
            packet=loader(BASE+'all/scoreboard?dates='+day+'&limit=1000')
            if not isinstance(packet.get('events'),list):raise ValueError('Unexpected scoreboard')
            return packet,False
        except Exception:return {'events':[]},True
    with ThreadPoolExecutor(max_workers=3) as pool:replies=list(pool.map(fetch,days))
    return dict(games=select_daily_events([p for p,_ in replies],chosen),failures=sum(failed for _,failed in replies),
                asOf=datetime.now(timezone.utc).isoformat())
