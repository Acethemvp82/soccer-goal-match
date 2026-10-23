import unittest
from datetime import datetime,timezone,timedelta
from extra_leagues import derived_minutes,minute_mark,current_lineups,history_from_summaries,diagnostic

NOW=datetime(2026,10,23,12,tzinfo=timezone.utc)
def player(starter=True,subbedIn=False,subbedOut=False,plays=None):
 return dict(starter=starter,subbedIn=subbedIn,subbedOut=subbedOut,plays=plays or [],stats=[{'name':'totalGoals','value':0},{'name':'totalShots','value':1}])
def substitution(clock):return dict(substitution=True,clock={'displayValue':clock})
class ExtraLeagueTests(unittest.TestCase):
 def test_minutes_do_not_invent_missing_substitution(self):
  self.assertEqual(derived_minutes(player()),90)
  self.assertIsNone(derived_minutes(player(subbedOut=True)))
  self.assertIsNone(derived_minutes(player(starter=False,subbedIn=True)))
  self.assertEqual(derived_minutes(player(subbedOut=True,plays=[substitution("65'")])),65)
  self.assertEqual(derived_minutes(player(starter=False,subbedIn=True,plays=[substitution("65'")])),25)
 def test_stoppage_time_and_red_card(self):
  self.assertEqual(minute_mark("90'+4'"),90)
  self.assertEqual(derived_minutes(player(starter=False,subbedIn=True,plays=[substitution("90'+4'")])),1)
  p=player(plays=[dict(redCard=True,clock={'displayValue':"39'"})]);self.assertEqual(derived_minutes(p),39)
 def test_duplicate_or_partial_starting_xi_not_confirmed(self):
  game=dict(id=1,team_h=1,team_a=2)
  summary={'header':{'id':'1','competitions':[{'status':{'type':{'state':'pre'}}}]},'rosters':[{'homeAway':'home','team':{'id':'1'},'roster':[{'starter':True,'athlete':{'id':'8'}} for _ in range(11)]}]}
  self.assertEqual(current_lineups([game],{1:summary}),{})
  summary['rosters'][0]['roster']=[{'starter':True,'athlete':{'id':str(i)}} for i in range(11)]
  self.assertEqual(len(current_lineups([game],{1:summary})),11)
  summary['header']['id']='2';self.assertEqual(current_lineups([game],{1:summary}),{})
 def test_missing_shots_not_treated_as_zero(self):
  game=dict(id=1,team_h=1,team_a=2,kickoff_time=(NOW-timedelta(days=1)).isoformat())
  entry=player();entry['athlete']={'id':'8','displayName':'Test'};entry['position']={'name':'Forward'};entry['stats']=[{'name':'totalGoals','value':1}]
  summary={'header':{'id':'1','competitions':[{'status':{'type':{'state':'post'}}}]},'rosters':[{'homeAway':'home','team':{'id':'1'},'roster':[entry]}]}
  result=history_from_summaries([game],{1:summary});self.assertEqual(result['histories'],{});self.assertEqual(result['missingEntries'],1)
 def test_basic_diagnostic_excludes_its_target_outcome(self):
  games=[];histories={1:[]}
  for i,days in enumerate([16,12,8,4],1):
   kickoff=(NOW-timedelta(days=days)).isoformat();games.append(dict(id=i,kickoff_time=kickoff,finished=True,team_h=1,team_a=2,team_h_score=1,team_a_score=1))
   histories[1].append(dict(fixture=i,kickoff_time=kickoff,minutes=75,starts=1,goals_scored=int(i==1),shots=3,team=1,opponent_team=2))
  context=dict(games=games,histories=histories,players={1:{'position':'FWD'}})
  a=diagnostic(context);histories[1][-1]['goals_scored']=8;histories[1][-1]['shots']=20;b=diagnostic(context)
  self.assertEqual(len(a),1);self.assertEqual(a[0]['probability'],b[0]['probability']);self.assertNotEqual(a[0]['scored'],b[0]['scored'])
if __name__=='__main__':unittest.main()
