"""Conservative FPL-to-ESPN lineup matching. Ambiguity remains unconfirmed."""
from datetime import timedelta
from analysis_tools import normalize_name
from model import parse_time

TEAM_ALIASES = {'nottinghamforest':'nottmforest','afcbournemouth':'bournemouth','brightonhovealbion':'brighton','brightonandhovealbion':'brighton','manchesterunited':'manutd','manchestercity':'mancity','wolverhamptonwanderers':'wolves','tottenhamhotspur':'spurs','ipswichtown':'ipswich','coventrycity':'coventry','hullcity':'hull','leedsunited':'leeds','westhamunited':'westham','newcastleunited':'newcastle','leicestercity':'leicester','lutontown':'luton'}
def team_key(name):
    name=normalize_name(name)
    return TEAM_ALIASES.get(name,name)

def match_event(fixture,teams,events):
    matches=[]
    for event in events:
        competitions=event.get('competitions',[])
        if not competitions:
            continue
        c=competitions[0]
        if c.get('status',event.get('status',{})).get('type',{}).get('state')!='pre':
            continue
        if not event.get('date') or abs(parse_time(event['date'])-parse_time(fixture['kickoff_time']))>timedelta(minutes=10):
            continue
        competitors={x.get('homeAway'):x for x in c.get('competitors',[])}
        def same(side,team_id):
            t=competitors.get(side,{}).get('team',{})
            names=[t.get('displayName',''),t.get('name',''),t.get('shortDisplayName','')]
            return any(team_key(name)==team_key(teams[team_id]['name']) for name in names if name)
        if same('home',fixture['team_h']) and same('away',fixture['team_a']):
            matches.append(event)
    return matches[0] if len(matches)==1 else None

def parse_lineups(fixture,players,summary):
    mapping={}
    header=summary.get('header',{})
    if header.get('competitions') and header['competitions'][0].get('status',{}).get('type',{}).get('state')!='pre':
        return mapping
    for roster in summary.get('rosters',[]):
        side=roster.get('homeAway')
        if side not in ('home','away'):
            continue
        team_id=fixture['team_h'] if side=='home' else fixture['team_a']
        entries=roster.get('roster',[])
        # A projected/partial or absent XI must never be treated as confirmed.
        if sum(e.get('starter') is True for e in entries)!=11:
            continue
        aliases={}
        for p in players:
            if p['team']!=team_id:
                continue
            for alias in [p.get('web_name'), ' '.join([p.get('first_name',''),p.get('second_name','')])]:
                key=normalize_name(alias)
                if key:
                    aliases.setdefault(key,set()).add(p['id'])
        used=set()
        for entry in entries:
            athlete=entry.get('athlete',{})
            candidates=set()
            for key in ['fullName','displayName']:
                candidates.update(aliases.get(normalize_name(athlete.get(key)),set()))
            if len(candidates)!=1:
                continue
            player_id=next(iter(candidates))
            if player_id in used or not isinstance(entry.get('starter'),bool):
                continue
            used.add(player_id)
            mapping[(fixture['id'],player_id)]='Confirmed starter' if entry['starter'] else 'Confirmed bench'
    return mapping
