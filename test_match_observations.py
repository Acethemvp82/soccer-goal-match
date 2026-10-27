import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from match_observations import parse_match_observations, screen_player, priced_record_issue
from extra_leagues import fetch_schedule, make_board

NOW=datetime(2026,10,26,5,tzinfo=timezone.utc)
GAME=dict(id=401876920,team_h=10125,team_a=225,kickoff_time='2026-10-26T03:10Z',started=True,finished=False)

def summary():
    return {'header':{'id':'401876920','competitions':[{'competitors':[{'homeAway':'home','team':{'id':'10125','displayName':'Tijuana'},'score':'4'},{'homeAway':'away','team':{'id':'225','displayName':'Santos'},'score':'1'}],'status':{'type':{'state':'in'},'displayClock':"83'"}}]},'rosters':[{'homeAway':'away','team':{'id':'225'},'roster':[{'athlete':{'id':'1','displayName':'Test'},'starter':True,'subbedOut':True,'stats':[{'name':'totalShots','value':2},{'name':'totalGoals','value':0}]}]}]}

class MatchTests(unittest.TestCase):
    def test_shots_are_observations_and_missing_is_not_zero(self):
        result=parse_match_observations(GAME,summary())
        self.assertEqual(result['rows'][0]['Player status'],'Substituted off')
        self.assertEqual(result['rows'][0]['Shots'],2)
        self.assertIsNone(result['rows'][0]['Shots on target'])
        self.assertNotIn('probability',result['rows'][0])
        packet=summary();packet['rosters'][0]['roster'][0]['stats'].append({'name':'redCards','value':1})
        self.assertEqual(parse_match_observations(GAME,packet)['rows'][0]['Player status'],'Sent off')

    def test_wrong_event_or_team_is_rejected(self):
        packet=summary();packet['header']['id']='other'
        with self.assertRaises(ValueError):parse_match_observations(GAME,packet)
        packet=summary();packet['header']['competitions'][0]['competitors'][0]['team']['id']='999'
        with self.assertRaises(ValueError):parse_match_observations(GAME,packet)

    def test_provider_day_before_midnight_is_requested(self):
        urls=[]
        def fetch(url):
            urls.append(url)
            events=[]
            if url.endswith('20261025'):
                events=[{'id':'401876920','date':'2026-10-26T03:10Z','competitions':[{'status':{'type':{'state':'in'}},'competitors':[{'homeAway':'home','team':{'id':'10125'}},{'homeAway':'away','team':{'id':'225'}}]}]}]
            return {'leagues':[{'season':{'year':2026}}],'events':events}
        with patch('extra_leagues.fetch_url',side_effect=fetch):
            schedule=fetch_schedule('mex.1','2026-10-26')
        self.assertTrue(any(u.endswith('20261025') for u in urls))
        self.assertEqual([g['id'] for g in schedule['games']],[401876920])
        self.assertTrue(schedule['games'][0]['started'])
        # Started games are never re-created as pregame predictions.
        self.assertEqual(make_board('mex.1',schedule['games'],dict(histories={},players={},games=[]),{}, {},NOW),[])

    def test_screen_requires_starter_history_minutes_and_checks(self):
        row=dict(kickoff=(NOW+timedelta(hours=1)).isoformat(),probability=.3,available=True,lineup='Confirmed starter',limited=False,historyGames=6,minutes=75,readiness='Inputs checked — basic unvalidated')
        self.assertEqual(screen_player(row,NOW),'Inputs screened — unvalidated')
        self.assertEqual(screen_player(dict(row,minutes=45),NOW),'Minutes concern')
        self.assertEqual(screen_player(dict(row,lineup='Unconfirmed'),NOW),'Await starting XI')
        self.assertEqual(screen_player(dict(row,readiness='History incomplete — review'),NOW),'Review data checks')
        self.assertEqual(screen_player(dict(row,kickoff=GAME['kickoff_time']),NOW),'Closed — match started')

class PricedRecordTests(unittest.TestCase):
    def setUp(self):
        self.row=dict(kickoff=(NOW+timedelta(hours=1)).isoformat(),asOf=(NOW-timedelta(minutes=1)).isoformat(),probability=.3,available=True,lineup='Confirmed starter',limited=False,historyGames=6,minutes=75,readiness='Inputs checked — basic unvalidated')
        self.price_time=(NOW-timedelta(minutes=1)).isoformat()
    def test_screen_and_timestamps_gate_new_record(self):
        self.assertIsNone(priced_record_issue(self.row,NOW,self.price_time,True))
        for field,value in [('lineup','Unconfirmed'),('lineup','Confirmed bench'),('minutes',45),('historyGames',1),('limited',True),('readiness','History incomplete — review')]:
            self.assertIsNotNone(priced_record_issue(dict(self.row,**{field:value}),NOW,self.price_time,True))
        self.assertIsNotNone(priced_record_issue(self.row,NOW,self.price_time,False))
        self.assertIsNotNone(priced_record_issue(self.row,NOW,self.price_time,True,stale=True))
    def test_expired_forecast_future_price_and_kickoff_boundary(self):
        self.assertIsNotNone(priced_record_issue(dict(self.row,asOf=(NOW-timedelta(minutes=11)).isoformat()),NOW,self.price_time,True))
        self.assertIsNotNone(priced_record_issue(self.row,NOW,(NOW+timedelta(minutes=1)).isoformat(),True))
        self.assertIsNotNone(priced_record_issue(self.row,NOW,(NOW-timedelta(minutes=11)).isoformat(),True))
        self.assertIsNotNone(priced_record_issue(dict(self.row,kickoff=NOW.isoformat()),NOW,self.price_time,True))
        self.assertIsNotNone(priced_record_issue(dict(self.row,asOf='2026-10-26T00:00:00'),NOW,self.price_time,True))

if __name__=='__main__':unittest.main()

