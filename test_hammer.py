import unittest
from datetime import datetime, timezone, timedelta
from hammer import evaluate_hammer, annotate_hammers

NOW=datetime(2026,10,31,12,tzinfo=timezone.utc)
def candidate(**overrides):
    row=dict(id=1,fixture=10,teamRank=3,goalThreat=80,goalMatch=55,probability=.20,
             available=True,limited=False,seasonMinutes=600,historyGames=5,minutes=60,
             lineup='Confirmed starter',readiness='Inputs checked — unvalidated',
             kickoff=(NOW+timedelta(hours=1)).isoformat(),asOf=NOW.isoformat())
    row.update(overrides);return row

class HammerTests(unittest.TestCase):
    def test_boundaries_and_models_share_research_rule(self):
        self.assertEqual(evaluate_hammer(candidate(),NOW)['hammer'],'🔨')
        self.assertEqual(evaluate_hammer(candidate(readiness='Inputs checked — basic unvalidated'),NOW)['hammer'],'🔨')
        self.assertEqual(evaluate_hammer(candidate(asOf=(NOW-timedelta(minutes=10)).isoformat()),NOW)['hammer'],'🔨')
    def test_each_failed_requirement_withholds_marker(self):
        for overrides in [dict(teamRank=4),dict(teamRank=None),dict(goalThreat=79),dict(goalMatch=54),dict(probability=.199),dict(minutes=59),dict(limited=True),dict(seasonMinutes=None),dict(seasonMinutes=449),dict(available=False),dict(historyGames=2),dict(lineup='Unconfirmed'),dict(lineup='Confirmed bench'),dict(readiness='History incomplete — review'),dict(asOf=(NOW-timedelta(seconds=601)).isoformat()),dict(asOf=(NOW+timedelta(seconds=1)).isoformat()),dict(kickoff=NOW.isoformat()),dict(asOf=None),dict(asOf='2026-10-31T12:00:00')]:
            with self.subTest(overrides=overrides):
                result=evaluate_hammer(candidate(**overrides),NOW)
                self.assertEqual(result['hammer'],'')
                self.assertNotEqual(result['hammerReason'],'All requirements met')
    def test_missing_and_nonfinite_scoring_inputs_fail_closed(self):
        for field in ['teamRank','goalThreat','goalMatch','probability']:
            for value in [None,float('nan'),float('inf'),'invalid']:
                with self.subTest(field=field,value=value):
                    self.assertEqual(evaluate_hammer(candidate(**{field:value}),NOW)['hammer'],'')
    def test_annotation_preserves_model_inputs_and_fixture_scope(self):
        rows=[candidate(),candidate(fixture=11,lineup='Unconfirmed')]
        annotated=annotate_hammers(rows,NOW)
        self.assertEqual([r['hammer'] for r in annotated],['🔨',''])
        self.assertNotIn('hammer',rows[0])
        for original,result in zip(rows,annotated):
            self.assertTrue(all(result[k]==v for k,v in original.items()))
        self.assertEqual(annotated[0]['hammerRuleVersion'],'soccer-hammer-1.0')

if __name__=='__main__':unittest.main()
