"""Mocked Streamlit checks; no live feeds or sportsbook actions."""
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from model import rank_slate

ROOT=Path(__file__).resolve().parent
NOW=datetime.now(timezone.utc)
KICK=(NOW+timedelta(hours=3)).isoformat()
GAME=dict(id=10,kickoff_time=KICK,team_h=1,team_a=2,home={'id':'1','displayName':'Home'},away={'id':'2','displayName':'Away'},started=False,finished=False)
BASE=dict(id=1,fixture=10,name='Qualified Scorer',short='Qualified Scorer',team='HOM',teamName='Home',opponent='AWY',home=True,position='FWD',kickoff=KICK,seasonMinutes=600,goals=3,shots=20,xg=3.2,xg90=.48,goalThreat=90,goalMatch=60,minutes=75,probability=.30,probabilityLow=.25,probabilityHigh=.34,available=True,availability='Available',lineup='Confirmed starter',limited=False,news='',readiness='Inputs checked — unvalidated',modelVersion='2.0',modelBasis='EPL xG-led',asOf=NOW.isoformat(),sourceAsOf=NOW.isoformat(),historyGames=6)
ROWS=rank_slate([BASE,dict(BASE,id=2,name='Below Threshold',short='Below Threshold',probability=.19)])
SCHEDULE=dict(games=[GAME],season=2026,scheduleFailures=0,asOf=NOW.isoformat())
CONTEXT=dict(requestedMatches=1,failedMatches=[],missingEntries=0,scheduleErrors=0,usableMatches=1,games=[],histories={},players={})
BOARD=dict(rows=ROWS,fixtures=[dict(id=10,home='HOM',away='AWY',kickoff=KICK)],asOf=NOW.isoformat(),_bootstrap={'elements':[],'teams':[{'id':1},{'id':2}]},_fixtures=[GAME])
def table(app):return next(x.value for x in app.dataframe if 'Player' in x.value.columns)
def extra_data(code,date):return rank_slate([dict(r,league=code,readiness='Inputs checked — basic unvalidated') for r in ROWS]),SCHEDULE,CONTEXT,[],{}

class HammerUI(unittest.TestCase):
    def test_epl_marker_filter_and_empty_filter_do_not_change_rank(self):
        with patch('data_source.fetch_board',return_value=BOARD),patch('data_source.load_histories',return_value=({},[])),patch('analysis_tools.enrich_rows',side_effect=lambda rows,*a,**k:rank_slate(rows)):
            app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=30).run()
            self.assertFalse(app.exception,app.exception)
            frame=table(app);self.assertEqual(frame['🔨'].tolist(),['🔨',''])
            self.assertEqual(list(frame.columns)[list(frame.columns).index('Player')-1],'🔨')
            self.assertEqual(frame['League rank'].tolist(),[1,2])
            next(c for c in app.checkbox if c.label=='🔨 Qualifiers only').check().run()
            self.assertFalse(app.exception,app.exception)
            self.assertEqual(len(table(app)),1)
            self.assertEqual(table(app)['Final Anytime'].iloc[0],30)
            next(t for t in app.text_input if t.label=='Player search').input('Below Threshold').run()
            self.assertFalse(app.exception,app.exception)
            self.assertTrue(any('No players match' in i.value for i in app.info))

    def test_other_and_combined_leagues_use_same_marker(self):
        with patch('league_board.load_schedule',return_value=SCHEDULE),patch('league_board.slate_data',side_effect=extra_data):
            app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=30)
            app.session_state['league_selection']='fra.1';app.run()
            self.assertFalse(app.exception,app.exception)
            self.assertEqual(table(app)['🔨'].tolist(),['🔨',''])
            next(c for c in app.checkbox if c.label=='🔨 Qualifiers only').check().run()
            self.assertEqual(len(table(app)),1)
            app.radio[0].set_value('Combined daily board').run()
            next(m for m in app.multiselect if m.label=='Competitions to combine').set_value(['fra.1','ger.1']).run()
            next(b for b in app.button if b.label=='Load selected competitions').click().run()
            self.assertFalse(app.exception,app.exception)
            self.assertEqual(table(app)['🔨'].tolist(),['🔨','','🔨',''])
            next(c for c in app.checkbox if c.label=='🔨 Qualifiers only').check().run()
            self.assertFalse(app.exception,app.exception)
            self.assertEqual(len(table(app)),2)
            self.assertEqual(set(table(app)['League rank']),{1})

if __name__=='__main__':unittest.main()
