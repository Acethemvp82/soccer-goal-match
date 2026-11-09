"""Isolated UI tests with fixed, complete model inputs and no external requests."""
import sys
import unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
from streamlit.testing.v1 import AppTest
from simulation import analytic

ROOT=Path(__file__).resolve().parent
CODE="""
from simulation_ui import render_simulator
import streamlit as st
render_simulator(st.session_state['test_rows'],'test_')
"""
def rows():
    now=datetime.now(timezone.utc)
    r=dict(id=1,fixture=2,league='eng.1',name='Test Scorer',team='H',opponent='A',rate=.6,adjustment=1.2,
           minutesProfile=dict(startShare=.75,starterMinutes=80,benchMinutes=20),
           kickoff=(now+timedelta(hours=2)).isoformat(),asOf=now.isoformat(),available=True,
           readiness='Await starting XI',lineup='Unconfirmed',modelVersion='2.0',overallRank=1,teamRank=1)
    r['probability']=analytic(r)
    return [r]

class SimulationUI(unittest.TestCase):
    def test_opt_in_run_invalidation_export_and_confirmed_filter(self):
        app=AppTest.from_string(CODE,default_timeout=20)
        app.session_state['test_rows']=rows();app.run()
        self.assertFalse(app.exception,app.exception)
        self.assertFalse(any(b.label=='Run 10,000 scoring simulations' for b in app.button))
        app.checkbox[0].check().run()
        next(b for b in app.button if b.label=='Run 10,000 scoring simulations').click().run()
        self.assertFalse(app.exception,app.exception)
        frame=next(d.value for d in app.dataframe if 'Simulated Anytime' in d.value.columns)
        self.assertEqual(len(frame),1)
        self.assertEqual(frame['Board league rank'].iloc[0],1)
        self.assertTrue(any(b.label=='Download simulation results' for b in app.get('download_button')))
        next(s for s in app.selectbox if s.label=='Minutes scenario').set_value(15).run()
        self.assertFalse(app.exception,app.exception)
        self.assertTrue(any('Inputs/settings changed' in i.value for i in app.info))
        self.assertFalse(any(b.label=='Download simulation results' for b in app.get('download_button')))
        next(c for c in app.checkbox if c.label=='Simulate confirmed starters only').check().run()
        self.assertFalse(app.exception,app.exception)
        self.assertTrue(any('No current, complete' in i.value for i in app.info))
    def test_sorting_preserves_seeded_results_but_follows_board_order(self):
        app=AppTest.from_string(CODE,default_timeout=20)
        source=rows();source.append(dict(source[0],id=2,name='Second Scorer',overallRank=2))
        app.session_state['test_rows']=source;app.run()
        app.checkbox[0].check().run()
        next(b for b in app.button if b.label=='Run 10,000 scoring simulations').click().run()
        first=next(d.value for d in app.dataframe if 'Simulated Anytime' in d.value.columns)
        app.session_state['test_rows']=list(reversed(source));app.run()
        self.assertFalse(app.exception,app.exception)
        second=next(d.value for d in app.dataframe if 'Simulated Anytime' in d.value.columns)
        self.assertEqual(second['Player'].tolist(),list(reversed(first['Player'].tolist())))
        self.assertEqual(second['Simulated Anytime'].tolist(),list(reversed(first['Simulated Anytime'].tolist())))

    def test_changed_inputs_and_kickoff_remove_results(self):
        app=AppTest.from_string(CODE,default_timeout=20)
        source=rows();app.session_state['test_rows']=source;app.run()
        app.checkbox[0].check().run()
        next(b for b in app.button if b.label=='Run 10,000 scoring simulations').click().run()
        changed=dict(source[0],rate=.8);changed['probability']=analytic(changed)
        app.session_state['test_rows']=[changed];app.run()
        self.assertTrue(any('Inputs/settings changed' in i.value for i in app.info))
        app.session_state['test_rows']=[dict(changed,kickoff=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat())];app.run()
        self.assertFalse(app.exception,app.exception)
        self.assertTrue(any('No current, complete' in i.value for i in app.info))
        self.assertFalse(any(b.label=='Download simulation results' for b in app.get('download_button')))

if __name__=='__main__':unittest.main()
