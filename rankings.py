"""Pregame rank tracking; snapshots live only in the current browser session."""
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st


def track_rank_changes(rows, snapshots):
    """Compare only changed inputs, so widget reruns do not erase movement."""
    groups = defaultdict(list)
    for row in rows:
        groups[row.get('league', 'eng.1')].append(row)
    output = []
    for league, group in groups.items():
        scope = (league, tuple(sorted({str(r['fixture']) for r in group})))
        fingerprint = tuple(sorted((str(r['fixture']), str(r['id']), r.get('probability'), r['available'], r['lineup'], r.get('minutes'), r.get('goalThreat'), r.get('goalMatch'), r.get('position')) for r in group))
        previous = snapshots.get(scope)
        current = {(str(r['fixture']), str(r['id'])): r.get('overallRank') for r in group}
        if previous is None or previous['fingerprint'] != fingerprint:
            changes = {}
            for identity, rank in current.items():
                old = previous['ranks'].get(identity) if previous else None
                changes[identity] = '—' if rank is None else 'New' if old is None else f'↑ {old-rank}' if old > rank else f'↓ {rank-old}' if old < rank else 'Unchanged'
            snapshots[scope] = dict(fingerprint=fingerprint, ranks=current, changes=changes)
        snapshot = snapshots[scope]
        for row in group:
            output.append(dict(row, rankChange=snapshot['changes'][(str(row['fixture']), str(row['id']))]))
    while len(snapshots) > 64:
        del snapshots[next(iter(snapshots))]
    # Preserve the caller's row order (groups can be interleaved).
    lookup = {(r.get('league', 'eng.1'), str(r['fixture']), str(r['id'])): r for r in output}
    return [lookup[(r.get('league', 'eng.1'), str(r['fixture']), str(r['id']))] for r in rows]


def prepare_rankings(rows):
    snapshots = st.session_state.setdefault('pregame_rank_snapshots', {})
    return track_rank_changes(rows, snapshots)


def ranking_controls(key):
    st.subheader('Live pregame player rankings')
    checked = datetime.now(ZoneInfo('America/New_York')).strftime('%b %d · %I:%M:%S %p ET')
    st.caption(f'Board calculated {checked} · Refreshes every 2 minutes while open. Source caches can be older; see data timestamps below. Rank change compares changed boards in this browser session; New marks the first observation. Rankings use Final Anytime within each league, before filters.')
    a, b = st.columns(2)
    order = a.selectbox('Sort players by', ['Final Anytime', 'Goal Threat', 'Goal Match'], key=key+'rank_sort')
    limit = b.selectbox('Ranking view', ['All players', 'Top 10 per league', 'Top 25 per league'], key=key+'rank_limit')
    return order, limit


def order_rankings(rows, order, limit):
    field = {'Final Anytime': 'probability', 'Goal Threat': 'goalThreat', 'Goal Match': 'goalMatch'}[order]
    n = {'All players': None, 'Top 10 per league': 10, 'Top 25 per league': 25}[limit]
    selected = [r for r in rows if n is None or (r.get('overallRank') is not None and r['overallRank'] <= n)]
    return sorted(selected, key=lambda r: (r.get('league', 'eng.1'), r.get(field) is None, -(r.get(field) or 0), r['name'], str(r['fixture'])))
