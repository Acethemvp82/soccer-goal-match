import unittest
from datetime import datetime, timezone, timedelta
import pandas as pd
from analysis_tools import american_to_decimal, compare_odds, minutes_profile, mixture_probability, past_history, walk_forward, grade_snapshot
from lineups import parse_lineups, match_event

NOW=datetime(2026,10,23,12,tzinfo=timezone.utc)

def history(days, goals=0, minutes=75, starts=1, fixture=1):
    return dict(kickoff_time=(NOW-timedelta(days=days)).isoformat(),fixture=fixture,minutes=minutes,starts=starts,expected_goals='.3',goals_scored=goals,opponent_team=2,was_home=True)

class AnalysisTests(unittest.TestCase):
    def test_odds_math_and_invalid_prices(self):
        self.assertEqual(american_to_decimal(300),4)
        self.assertAlmostEqual(american_to_decimal(-200),1.5)
        v=compare_odds(.3,300)
        self.assertAlmostEqual(v['breakEven'],.25)
        self.assertAlmostEqual(v['expectedReturn'],.2)
        for price in [0,50,-50,float('nan'),float('inf')]:
            with self.assertRaises(ValueError):american_to_decimal(price)
    def test_starter_bench_minutes_and_sensitivity(self):
        h=[history(8,minutes=80),history(6,minutes=70),history(4,minutes=20,starts=0),history(2,minutes=0,starts=0)]
        starter=minutes_profile(h,'Confirmed starter');bench=minutes_profile(h,'Confirmed bench')
        self.assertEqual(starter['minutes'],75)
        self.assertEqual(bench['minutes'],20)
        self.assertGreater(mixture_probability(.5,starter,1),mixture_probability(.5,bench,1))
        self.assertLess(mixture_probability(.5,starter,1,-15),mixture_probability(.5,starter,1))
        self.assertIsNone(minutes_profile([history(2,minutes=20,starts=0)],'Confirmed starter'))
    def test_same_match_outcomes_never_enter_inputs(self):
        before=history(5);same=history(0)
        self.assertEqual(past_history([same,before],NOW),[before])
        player=dict(id=1,element_type=4)
        h=[history(12,fixture=1),history(9,fixture=2),history(6,fixture=3),history(3,fixture=4,goals=0)]
        fixtures=[dict(id=i+1,finished=True,kickoff_time=r['kickoff_time'],team_h=1,team_a=2,team_h_score=1,team_a_score=1) for i,r in enumerate(h)]
        first=walk_forward([player],{1:h},fixtures,NOW)
        h[-1]=dict(h[-1],goals_scored=5,expected_goals='9.9',minutes=90)
        second=walk_forward([player],{1:h},fixtures,NOW)
        self.assertEqual(len(first),1)
        self.assertEqual(first[0]['probability'],second[0]['probability'])
        self.assertNotEqual(first[0]['scored'],second[0]['scored'])
    def test_priced_record_paper_settlement(self):
        f=dict(id=4,finished=True,kickoff_time=NOW.isoformat())
        row=dict(id=1,fixture=4,asOf=(NOW-timedelta(hours=2)).isoformat(),probability=.3,modelVersion='2.0',americanOdds=300,oddsRecordedAt=(NOW-timedelta(hours=1)).isoformat(),nonappearanceRule='void')
        win=grade_snapshot(pd.DataFrame([row]),{1:[dict(fixture=4,minutes=80,goals_scored=2)]},[f])
        self.assertEqual(win.iloc[0]['Paper return / $1'],3)
        loss=grade_snapshot(pd.DataFrame([row]),{1:[dict(fixture=4,minutes=80,goals_scored=0)]},[f])
        self.assertEqual(loss.iloc[0]['Paper return / $1'],-1)
        with self.assertRaises(ValueError):grade_snapshot(pd.DataFrame([dict(row,oddsRecordedAt=NOW.isoformat())]),{},[f])

    def test_partial_xi_and_ambiguous_names_not_confirmed(self):
        fixture=dict(id=1,team_h=1,team_a=2)
        players=[dict(id=1,team=1,first_name='Test',second_name='Player',web_name='Player')]
        entry=dict(starter=True,athlete={'fullName':'Test Player'})
        partial={'rosters':[{'homeAway':'home','roster':[entry]}]}
        self.assertEqual(parse_lineups(fixture,players,partial),{})
        complete={'rosters':[{'homeAway':'home','roster':[entry]+[dict(starter=True,athlete={'fullName':f'Other {i}'}) for i in range(10)]}]}
        self.assertEqual(parse_lineups(fixture,players,complete),{(1,1):'Confirmed starter'})
        duplicate=players+[dict(players[0],id=2)]
        self.assertEqual(parse_lineups(fixture,duplicate,complete),{})
    def test_wrong_match_cannot_confirm_xi(self):
        f=dict(team_h=1,team_a=2,kickoff_time=NOW.isoformat())
        teams={1:{'name':'Ipswich'},2:{'name':"Nott'm Forest"}}
        event=dict(date=NOW.isoformat(),competitions=[dict(status={'type':{'state':'pre'}},competitors=[dict(homeAway='home',team={'displayName':'Ipswich Town'}),dict(homeAway='away',team={'displayName':'Nottingham Forest'})])])
        self.assertIsNotNone(match_event(f,teams,[event]))
        self.assertIsNone(match_event(dict(f,kickoff_time=(NOW+timedelta(hours=1)).isoformat()),teams,[event]))
    def test_grading_excludes_dnp_and_rejects_postgame_snapshot(self):
        f=dict(id=4,finished=True,kickoff_time=NOW.isoformat())
        row=dict(id=1,fixture=4,asOf=(NOW-timedelta(hours=2)).isoformat(),probability=.3,modelVersion='2.0')
        graded=grade_snapshot(pd.DataFrame([row]),{1:[dict(fixture=4,minutes=0,goals_scored=0)]},[f])
        self.assertEqual(graded.iloc[0]['Status'],'DNP — excluded')
        self.assertTrue(pd.isna(graded.iloc[0]['Scored']))
        with self.assertRaises(ValueError):grade_snapshot(pd.DataFrame([dict(row,asOf=NOW.isoformat())]),{},[f])
        with self.assertRaises(ValueError):grade_snapshot(pd.DataFrame([row,row]),{},[f])

if __name__=='__main__':unittest.main()
