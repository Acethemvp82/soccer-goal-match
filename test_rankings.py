import unittest
from model import rank_slate
from rankings import track_rank_changes, order_rankings


def player(pid, probability, league='eng.1', **overrides):
    return dict(id=pid, fixture=1, name=str(pid), team='A', position='FWD',
                probability=probability, available=True, limited=False,
                lineup='Unconfirmed', league=league, minutes=80,
                goalThreat=80, goalMatch=50, **overrides)


class RankingsTest(unittest.TestCase):
    def test_league_scope_and_missing_estimates(self):
        rows=rank_slate([player(1,.5),player(2,.4,'fra.1'),player(3,None)])
        self.assertEqual([r['overallRank'] for r in rows],[1,1,None])
        self.assertEqual([r['positionRank'] for r in rows],[1,1,None])

    def test_change_survives_widget_rerun_and_is_scoped(self):
        snapshots={}
        first=track_rank_changes(rank_slate([player(1,.3),player(2,.2)]),snapshots)
        self.assertEqual(first[0]['rankChange'],'New')
        rows=rank_slate([player(1,.3),player(2,.4)])
        changed=track_rank_changes(rows,snapshots)
        self.assertEqual([r['rankChange'] for r in changed],['↑ 1','↓ 1'])
        self.assertEqual(track_rank_changes(rows,snapshots),changed)
        other=track_rank_changes(rank_slate([player(1,.3,'fra.1')]),snapshots)
        self.assertEqual(other[0]['rankChange'],'New')

    def test_top_limit_uses_unfiltered_final_anytime_rank(self):
        rows=rank_slate([player(i,.5-i/100) for i in range(1,13)])
        rows[-1]['goalThreat']=100
        ordered=order_rankings(rows,'Goal Threat','Top 10 per league')
        self.assertEqual(len(ordered),10)
        self.assertNotIn(12,[r['id'] for r in ordered])
        # Filtering does not promote #11 into the top ten.
        self.assertEqual(order_rankings(rows[10:],'Final Anytime','Top 10 per league'),[])

if __name__=='__main__':unittest.main()
