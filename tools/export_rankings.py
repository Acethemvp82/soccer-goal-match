"""Standalone rankings JSON exporter. Does not import or modify the Streamlit app.

Usage:
  python tools/export_rankings.py soccer-multi-league-pregame.csv rankings.json

Input is the existing 'Export pregame board' CSV downloaded from Streamlit.
Only rows already calculated by the model are exported. This utility does not
fetch live rankings or publish to GitHub automatically.
"""
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ("league", "short", "team", "opponent", "teamRank", "overallRank",
          "goalThreat", "goalMatch", "probability", "lineup", "readiness",
          "fixture", "kickoff", "sourceAsOf", "modelVersion")


def export(input_path, output_path):
    with Path(input_path).open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    required = {"short", "team", "goalThreat", "goalMatch", "probability"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError("Expected a nonempty pregame board CSV with ranking fields")
    ranked = []
    for row in rows:
        if not row.get("probability"):
            continue
        item = {key: row.get(key) for key in FIELDS if key in row}
        for key in ("goalThreat", "goalMatch", "probability"):
            item[key] = float(item[key]) if item.get(key) not in ("", None) else None
        for key in ("teamRank", "overallRank"):
            if key in item:
                item[key] = int(float(item[key])) if item[key] not in ("", None) else None
        ranked.append(item)
    ranked.sort(key=lambda r: (-(r["probability"] or 0), r["short"]))
    payload = {
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "source": "Manually exported Streamlit pregame CSV; not an independently live feed",
        "count": len(ranked),
        "players": ranked,
    }
    Path(output_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return len(ranked)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python tools/export_rankings.py INPUT.csv OUTPUT.json")
    print(f"Exported {export(sys.argv[1], sys.argv[2])} players")
