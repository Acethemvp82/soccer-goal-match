import unittest
from datetime import date
from daily_fixtures import select_daily_events,fetch_daily_fixtures

def event(pid,home,away,kickoff,state):
    return dict(id=str(pid),date=kickoff,season={'slug':'league'},competitions=[dict(altGameNote='League',status={'type':{'state':state},'displayClock':"14'"},competitors=[{'homeAway':'home','team':{'id':'1','displayName':home},'score':'0'},{'homeAway':'away','team':{'id':'2','displayName':away},'score':'0'}])])
EVENTS=[event(401843480,'Kristiansund','Valerenga','2026-11-09T18:00Z','in'),event(401921368,'Mushuc Runa','Delfin','2026-11-09T18:00Z','in'),event(401921367,'Tecnico Universitario','Manta','2026-11-09T20:30Z','pre'),event(401877901,'Junior','Cucuta','2026-11-10T00:00Z','pre')]
class DailyFixturesTests(unittest.TestCase):
    def test_four_reported_games_survive_live_and_midnight_filters(self):
        games=select_daily_events([{'events':EVENTS}],date(2026,11,9))
        self.assertEqual(len(games),4)
        self.assertEqual(sum(g['state']=='in' for g in games),2)
        self.assertEqual(sum(g['state']=='pre' for g in games),2)
        self.assertTrue(any(g['id']==401877901 for g in games))
        self.assertEqual(games[0]['team_h_score'],0)
        self.assertIsNone(next(g for g in games if g['id']==401921367)['team_h_score'])
    def test_neighbor_days_are_requested_and_duplicate_ids_are_removed(self):
        urls=[]
        def loader(url):urls.append(url);return {'events':EVENTS}
        packet=fetch_daily_fixtures('2026-11-09',loader)
        self.assertEqual(len(packet['games']),4);self.assertEqual(packet['failures'],0)
        self.assertTrue(any('dates=20261108' in u for u in urls))
        self.assertTrue(any('dates=20261110' in u for u in urls))
    def test_partial_failure_is_reported_without_hiding_known_games(self):
        def loader(url):
            if 'dates=20261110' in url:raise OSError('Unavailable')
            return {'events':EVENTS}
        packet=fetch_daily_fixtures('2026-11-09',loader)
        self.assertEqual(packet['failures'],1);self.assertEqual(len(packet['games']),4)
        self.assertEqual(select_daily_events([{'events':EVENTS}],date(2026,11,11)),[])

if __name__=='__main__':unittest.main()
