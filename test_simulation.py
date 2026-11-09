import copy
import unittest
from datetime import datetime,timezone,timedelta
from simulation import analytic, eligibility_issue, signature, simulate_player, simulate_rows, RUNS

NOW=datetime(2026,11,9,12,tzinfo=timezone.utc)
def row(**overrides):
    r=dict(id=1,fixture=20,league='eng.1',name='Scorer',team='H',rate=.6,adjustment=1.2,
           minutesProfile=dict(startShare=.75,starterMinutes=80,benchMinutes=20),
           kickoff=(NOW+timedelta(hours=2)).isoformat(),asOf=NOW.isoformat(),available=True,
           readiness='Await starting XI',lineup='Unconfirmed',modelVersion='2.0',overallRank=1,teamRank=1,hammer='')
    r.update(overrides)
    r['probability']=analytic(r)
    return r

class SimulationTests(unittest.TestCase):
    def test_zero_one_multiple_counts_and_probability_reproduce_model(self):
        r=row();original=copy.deepcopy(r);result=simulate_player(r,NOW)
        self.assertEqual(result['zeroGoals']+result['oneGoal']+result['multipleGoals'],RUNS)
        self.assertEqual(result['oneGoal']+result['multipleGoals'],result['scoringRuns'])
        self.assertLess(abs(result['simulatedProbability']-r['probability']),.02)
        self.assertAlmostEqual(result['scenarioProbability'],r['probability'])
        self.assertLess(abs(result['meanGoals']-.6*1.2*(.75*80+.25*20)/90),.03)
        self.assertEqual(r,original)
    def test_reproducibility_and_league_fixture_identity(self):
        a=row();b=row(id=2)
        first=simulate_rows([a,b],NOW);second=simulate_rows([b,a],NOW)
        self.assertEqual(first[0],second[1]);self.assertEqual(first[1],second[0])
        self.assertEqual(signature([a,b],0),signature([b,a],0))
        self.assertNotEqual(first[0]['scoringRuns'],simulate_player(row(league='fra.1'),NOW)['scoringRuns'])
        with self.assertRaises(ValueError):simulate_rows([a,a],NOW)
    def test_minutes_scenarios_are_monotonic_and_capped(self):
        r=row();low=simulate_player(r,NOW,-15);high=simulate_player(r,NOW,15)
        self.assertLess(low['scenarioProbability'],high['scenarioProbability'])
        self.assertLess(low['simulatedProbability'],high['simulatedProbability'])
        self.assertNotEqual(signature([r],0),signature([r],15))
        capped=row(minutesProfile=dict(startShare=1,starterMinutes=90,benchMinutes=None))
        self.assertEqual(analytic(capped),analytic(capped,15))
    def test_zero_rate_and_observed_role_only(self):
        result=simulate_player(row(rate=0),NOW)
        self.assertEqual(result['zeroGoals'],RUNS);self.assertEqual(result['scoringRuns'],0)
        starter=row(minutesProfile=dict(startShare=1,starterMinutes=75,benchMinutes=None))
        self.assertIsNone(eligibility_issue(starter,NOW))
        bench=row(minutesProfile=dict(startShare=0,starterMinutes=None,benchMinutes=20),lineup='Confirmed bench',readiness='Bench — review rules')
        self.assertIsNone(eligibility_issue(bench,NOW))
    def test_stale_started_incomplete_and_mismatched_inputs_fail_closed(self):
        r=row()
        for changes in [dict(kickoff=NOW.isoformat()),dict(asOf=(NOW-timedelta(minutes=11)).isoformat()),dict(asOf=(NOW+timedelta(seconds=1)).isoformat()),dict(available=False),dict(rate=None),dict(rate=float('nan')),dict(adjustment=0),dict(minutesProfile={}),dict(probability=.99),dict(readiness='History incomplete — review')]:
            with self.subTest(changes=changes):
                invalid=dict(r,**changes)
                self.assertIsNotNone(eligibility_issue(invalid,NOW))
                with self.assertRaises(ValueError):simulate_player(invalid,NOW)
        self.assertIsNone(eligibility_issue(dict(r,asOf=(NOW-timedelta(minutes=10)).isoformat()),NOW))
    def test_actual_epl_and_basic_model_rows_reproduce_their_estimates(self):
        from analysis_tools import enrich_rows
        from extra_leagues import make_board
        history=[dict(fixture=i,kickoff_time=(NOW-timedelta(days=30-i*4)).isoformat(),minutes=75,starts=1,expected_goals='.4',goals_scored=int(i%3==0),shots=3,team=1,opponent_team=2) for i in range(1,7)]
        origin=dict(id=1,fixture=20,name='Scorer',short='Scorer',team='H',position='FWD',available=True,limited=False,adjustment=1.1,seasonMinutes=450,kickoff=(NOW+timedelta(hours=2)).isoformat())
        player=dict(id=1,element_type=4,minutes=450,expected_goals='2.4',goals_scored=2)
        epl=enrich_rows([origin],[player],{1:history},{(20,1):'Confirmed starter'},NOW)[0]
        game=dict(id=20,team_h=1,team_a=2,home={'id':'1','displayName':'Home'},away={'id':'2','displayName':'Away'},started=False,kickoff_time=origin['kickoff'])
        past=[dict(id=h['fixture'],kickoff_time=h['kickoff_time'],finished=True,team_h=1,team_a=2,team_h_score=1,team_a_score=1) for h in history]
        context=dict(histories={1:history},players={1:{'position':'FWD'}},games=past,failedMatches=[],missingEntries=0,asOf=NOW.isoformat())
        rosters={1:{'athletes':[{'id':'1','displayName':'Scorer','position':{'name':'Forward','abbreviation':'F'}}]}}
        basic=make_board('fra.1',[game],context,rosters,{(20,1):'Confirmed starter'},NOW)[0]
        for candidate in [epl,basic]:
            self.assertIsNone(eligibility_issue(candidate,NOW))
            self.assertAlmostEqual(analytic(candidate),candidate['probability'])
            result=simulate_player(candidate,NOW)
            self.assertLess(abs(result['simulatedProbability']-candidate['probability']),.02)

    def test_fixed_run_and_scenario_validation(self):
        for kwargs in [dict(runs=1000),dict(minutes_delta=30)]:
            with self.assertRaises(ValueError):simulate_player(row(),NOW,**kwargs)

if __name__=='__main__':unittest.main()
