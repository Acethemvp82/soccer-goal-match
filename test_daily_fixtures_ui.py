from copy import deepcopy
import unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from daily_fixtures import select_daily_events,ET
from test_daily_fixtures import event
from daily_fixtures_ui import best_match_summary

ROOT=Path(__file__).resolve().parent
NOW=datetime.now(timezone.utc)
DAY=NOW.astimezone(ET).date()
GAME=event(401921367,'Tecnico Universitario','Manta',(NOW+timedelta(hours=1)).isoformat(),'pre')
# Keep fixture on the date picked in this test, regardless of host clock.
GAMES=select_daily_events([{'events':[GAME]}],(NOW+timedelta(hours=1)).astimezone(ET).date())
DETAILS={'header':{'id':'401921367','league':{'slug':'ecu.1','name':'Ecuador Serie A'},'competitions':[{'competitors':GAME['competitions'][0]['competitors'],'status':{'type':{'state':'pre'}}}]},'rosters':[]}
class DailyUI(unittest.TestCase):
    def test_cross_competition_view_and_verified_league_navigation(self):
        packet={'games':GAMES,'failures':0,'asOf':NOW.isoformat()}
        schedule={'games':GAMES,'season':2026,'scheduleFailures':0,'asOf':NOW.isoformat()}
        with patch('daily_fixtures_ui.load_daily',return_value=packet),patch('daily_fixtures_ui.load_daily_summary',return_value={'summary':DETAILS,'asOf':NOW.isoformat()}),patch('league_board.load_schedule',return_value=schedule),patch('league_board.slate_data',return_value=([],schedule,None,[],{})):
            app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=20)
            app.session_state['board_view']="Today's matches";app.run()
            self.assertFalse(app.exception,app.exception)
            self.assertTrue(any('Match' in d.value.columns for d in app.dataframe))
            next(c for c in app.checkbox if c.label=='Load selected match details').check().run()
            self.assertFalse(app.exception,app.exception)
            next(b for b in app.button if b.label=='Open this league’s board').click().run()
            self.assertFalse(app.exception,app.exception)
            self.assertEqual(app.session_state['board_view'],'Single league')
            self.assertEqual(app.session_state['league_selection'],'ecu.1')
    def test_shortcut_opens_exact_match_without_details(self):
        packet={'games':GAMES,'failures':0,'asOf':NOW.isoformat()}
        schedule={'games':GAMES,'season':2026,'scheduleFailures':0,'asOf':NOW.isoformat()}
        with patch('daily_fixtures_ui.load_daily',return_value=packet),patch('daily_fixtures_ui.load_daily_summary',return_value={'summary':DETAILS,'asOf':NOW.isoformat()}),patch('league_board.load_schedule',return_value=schedule),patch('league_board.slate_data',return_value=([],schedule,None,[],{})):
            app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=20)
            app.session_state['board_view']="Today's matches"
            app.run()
            next(b for b in app.button if b.label=='View scorer board').click().run()
            self.assertFalse(app.exception,app.exception)
            self.assertEqual(app.session_state['board_view'],'Single league')
            self.assertEqual(app.session_state['league_selection'],'ecu.1')
            self.assertEqual(app.session_state['extra_match'],GAMES[0]['id'])

    def test_search_does_not_invent_player_forecasts(self):
        packet={'games':GAMES,'failures':0,'asOf':NOW.isoformat()}
        with patch('daily_fixtures_ui.load_daily',return_value=packet):
            app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=20)
            app.session_state['board_view']="Today's matches";app.run()
            next(t for t in app.text_input if t.label=='Find today’s team or competition').input('no such team').run()
            self.assertFalse(app.exception,app.exception)
            self.assertTrue(any('No matches match' in i.value for i in app.info))
            self.assertFalse(any(b.label=='Run 10,000 scoring simulations' for b in app.button))

    def test_upcoming_and_live_have_separate_sections_and_finished_is_hidden(self):
        upcoming = dict(GAMES[0], matchLabel='Upcoming test')
        live = dict(upcoming, id=88, matchLabel='Live test', state='in', started=True,
                    team_h_score=1, team_a_score=0, clock='15 mins')
        finished = dict(live, id=99, matchLabel='Finished test', state='post', finished=True)
        with patch('daily_fixtures_ui.load_daily', return_value={'games':[upcoming,live,finished],'failures':0,'asOf':NOW.isoformat()}):
            app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=20)
            app.session_state['board_view']="Today's matches"
            app.run()
            self.assertFalse(app.exception,app.exception)
            self.assertEqual([d.value['Match'].tolist() for d in app.dataframe], [['Upcoming test'], ['Live test']])
            self.assertEqual(app.dataframe[1].value['Score'].tolist(), ['1–0'])

    def test_passed_kickoff_with_stale_summary_is_not_upcoming_or_live(self):
        game = dict(GAMES[0], kickoff_time=(NOW-timedelta(minutes=9)).isoformat())
        packet = {'games':[game], 'failures':0, 'asOf':NOW.isoformat()}
        status = {'summary':DETAILS, 'asOf':NOW.isoformat()}
        with patch('daily_fixtures_ui.load_daily', return_value=packet), patch('daily_fixtures_ui.load_daily_summary', return_value=status):
            app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=20)
            app.session_state['board_view']="Today's matches"
            app.run()
            self.assertEqual(app.dataframe[0].value['Status'].tolist(), ['Kickoff passed · awaiting feed'])
            next(c for c in app.checkbox if c.label=='Load selected match details').check().run()
            self.assertFalse(app.exception,app.exception)
            self.assertTrue(any('has not confirmed live play' in item.value for item in app.info))
            self.assertEqual(len(app.dataframe),1)

    def test_competition_summary_supplies_verified_live_player_rows(self):
        game = dict(GAMES[0], kickoff_time=(NOW-timedelta(minutes=9)).isoformat())
        detail = deepcopy(DETAILS)
        detail['header']['competitions'][0]['status'] = {'type':{'state':'in'},'displayClock':"9'"}
        detail['rosters'] = [{'homeAway':'home', 'team':{'id':str(game['team_h'])}, 'roster':[
            {'athlete':{'id':'88','displayName':'Live Player'},'stats':[{'name':'totalShots','value':1}]}
        ]}]
        broad = {'summary':DETAILS,'asOf':NOW.isoformat()}
        specific = {'summary':detail,'asOf':NOW.isoformat()}
        with patch('daily_fixtures_ui.load_daily_summary',side_effect=[broad,specific]) as fetch:
            _, observed = best_match_summary(game, NOW)
            self.assertEqual(fetch.call_args.args, (game['id'],'ecu.1'))
            self.assertEqual(observed['state'],'in')
            self.assertEqual(observed['rows'][0]['Shots'],1)

if __name__=='__main__':unittest.main()
