"""Copilot tool functions — ported from AIAgent draft-copilot.

Pure Python functions that compute roster analysis, value picks, and
positional scarcity from pre-computed ML model predictions. No LLM calls.
"""

import os
import pandas as pd
from functools import lru_cache
from unidecode import unidecode

PICKLE_DIR = os.path.join(os.path.dirname(__file__), "models")

FORMAT_ALIASES = {
    "ppr": "ppr",
    "full_ppr": "ppr",
    "half_ppr": "half_ppr",
    "halfppr": "half_ppr",
    "half-ppr": "half_ppr",
    "standard": "standard",
    "std": "standard",
    "te_premium": "ppr",
}

# Bye weeks for 2026 NFL season (projected)
BYE_WEEKS_2026 = {
    "ARI": 11, "ATL": 12, "BAL": 8, "BUF": 12, "CAR": 7, "CHI": 10,
    "CIN": 9, "CLE": 10, "DAL": 7, "DEN": 9, "DET": 6, "GB": 10,
    "HOU": 14, "IND": 14, "JAX": 11, "KC": 6, "LV": 10, "LAC": 8,
    "LA": 6, "MIA": 11, "MIN": 12, "NE": 14, "NO": 9, "NYG": 11,
    "NYJ": 12, "PHI": 5, "PIT": 9, "SF": 8, "SEA": 5, "TB": 11,
    "TEN": 7, "WAS": 14,
}


def _resolve_format(scoring_format):
    fmt = (scoring_format or "ppr").lower().strip()
    return FORMAT_ALIASES.get(fmt, "ppr")


def _normalize(name):
    return unidecode(name).lower().strip()


@lru_cache(maxsize=4)
def _load_predictions(scoring_format="ppr"):
    fmt = _resolve_format(scoring_format)
    path = os.path.join(PICKLE_DIR, f"combined_predictions_{fmt}.pkl")
    if not os.path.exists(path):
        return None
    return pd.read_pickle(path)


def _find_player(df, player_name):
    name_norm = _normalize(player_name)
    mask = df["player_name"].apply(_normalize) == name_norm
    if not mask.any():
        mask = df["player_name"].apply(_normalize).str.contains(name_norm, na=False)
    if not mask.any():
        return None
    return df[mask].iloc[0]


# ── Roster Analysis ────────────────────────────────────────────────

def analyze_roster(user_roster, roster_slots, scoring_format="ppr", num_teams=12):
    """Analyze roster and return positional needs + bye conflicts.

    Args:
        user_roster: list of {name, position} dicts
        roster_slots: dict like {QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 1, ...}
        scoring_format: ppr/half_ppr/standard
        num_teams: league size
    """
    position_counts = {"QB": 0, "RB": 0, "WR": 0, "TE": 0, "K": 0, "DST": 0}
    for player in user_roster:
        pos = (player.get("position") or "").upper()
        if pos in position_counts:
            position_counts[pos] += 1

    required = {
        "QB": int(roster_slots.get("QB", 1)),
        "RB": int(roster_slots.get("RB", 2)),
        "WR": int(roster_slots.get("WR", 2)),
        "TE": int(roster_slots.get("TE", 1)),
        "K": int(roster_slots.get("K", 0)),
        "DST": int(roster_slots.get("DST", 0)),
    }
    flex_count = int(roster_slots.get("FLEX", 0))
    superflex_count = int(roster_slots.get("SUPER_FLEX", 0) or roster_slots.get("SUPERFLEX", 0))
    bench_count = int(roster_slots.get("bench", 6))

    total_roster = sum(required.values()) + flex_count + superflex_count + bench_count
    total_drafted = len(user_roster)

    needs = []
    for pos in ["QB", "RB", "WR", "TE"]:
        have = position_counts[pos]
        need = required[pos]
        gap = max(0, need - have)
        if gap > 0:
            needs.append({
                "position": pos,
                "priority": "HIGH",
                "have": have,
                "starter_slots": need,
                "starter_gap": gap,
                "note": f"Need {gap} more {pos} to fill starter slots",
            })

    # FLEX consideration
    flex_eligible = position_counts["RB"] + position_counts["WR"] + position_counts["TE"]
    flex_needed = required["RB"] + required["WR"] + required["TE"] + flex_count
    flex_gap = max(0, flex_needed - flex_eligible)
    if flex_gap > 0 and flex_count > 0:
        needs.append({
            "position": "FLEX",
            "priority": "MEDIUM",
            "have": flex_eligible,
            "starter_slots": flex_needed,
            "starter_gap": flex_gap,
            "note": f"Need {flex_gap} more RB/WR/TE to fill flex slots",
        })

    # Superflex
    if superflex_count > 0:
        sf_eligible = sum(position_counts[p] for p in ["QB", "RB", "WR", "TE"])
        sf_needed = sum(required[p] for p in ["QB", "RB", "WR", "TE"]) + flex_count + superflex_count
        sf_gap = max(0, sf_needed - sf_eligible)
        if sf_gap > 0:
            needs.append({
                "position": "SUPERFLEX",
                "priority": "HIGH",
                "have": sf_eligible,
                "starter_slots": sf_needed,
                "starter_gap": sf_gap,
                "note": f"Need {sf_gap} more to fill superflex",
            })

    # Bye week conflicts
    bye_conflicts = []
    bye_weeks = {}
    for player in user_roster:
        team = (player.get("nfl_team") or player.get("team") or "").upper()
        if team in BYE_WEEKS_2026:
            bye = BYE_WEEKS_2026[team]
            bye_weeks.setdefault(bye, []).append(player.get("name", ""))
    for week, players in sorted(bye_weeks.items()):
        if len(players) >= 2:
            bye_conflicts.append({
                "week": week,
                "players": players,
                "count": len(players),
            })

    return {
        "roster_summary": {
            "total_drafted": total_drafted,
            "total_roster_size": total_roster,
            "picks_remaining": total_roster - total_drafted,
            "position_counts": position_counts,
        },
        "positional_needs": needs,
        "bye_week_conflicts": bye_conflicts,
    }


# ── Value Picks ────────────────────────────────────────────────────

def get_best_value_picks(available_players, current_pick, num_teams=12,
                         scoring_format="ppr", top_n=5):
    """Find best-value picks from available player dicts.

    Args:
        available_players: list of {name, position, ppg, vbd} dicts (from client)
        current_pick: overall pick number
        num_teams: league size
        scoring_format: scoring format
        top_n: how many to return
    """
    df = _load_predictions(scoring_format)
    if df is None:
        return []

    results = []
    for player in available_players:
        name = player.get("name", "")
        row = _find_player(df, name)
        if row is None:
            continue
        vbd_rank = int(row["rank"])
        value_delta = vbd_rank - current_pick
        results.append({
            "player_name": row["player_name"],
            "position": row["position"],
            "team": row.get("team", ""),
            "vbd_rank": vbd_rank,
            "value_delta": value_delta,
            "projected_ppg": round(float(row["predicted_ppg_2026"]), 2),
            "vbd": round(float(row["vbd"]), 2),
            "assessment": (
                "GREAT VALUE" if value_delta < -5
                else "GOOD VALUE" if value_delta < 0
                else "FAIR" if value_delta <= 5
                else "REACH"
            ),
        })

    results.sort(key=lambda x: x["value_delta"])
    return results[:top_n]


# ── Positional Scarcity ───────────────────────────────────────────

def get_positional_scarcity(available_players, scoring_format="ppr",
                            num_teams=12):
    """Analyze how many startable players remain at each position.

    Args:
        available_players: list of {name, position} dicts
        scoring_format: scoring format
        num_teams: league size (used for scarcity thresholds)
    """
    df = _load_predictions(scoring_format)
    if df is None:
        return {}

    scarcity = {}
    for pos in ["QB", "RB", "WR", "TE"]:
        available_at_pos = []
        for player in available_players:
            p_pos = (player.get("position") or "").upper()
            if p_pos != pos:
                continue
            name = player.get("name", "")
            row = _find_player(df, name)
            if row is None:
                continue
            available_at_pos.append({
                "player_name": row["player_name"],
                "projected_ppg": round(float(row["predicted_ppg_2026"]), 2),
                "vbd": round(float(row["vbd"]), 2),
            })

        available_at_pos.sort(key=lambda x: -x["projected_ppg"])
        above_replacement = [p for p in available_at_pos if p["vbd"] > 0]
        n_above = len(above_replacement)

        critical_threshold = max(2, num_teams // 3)
        tight_threshold = max(4, num_teams // 2)

        scarcity[pos] = {
            "total_available": len(available_at_pos),
            "above_replacement": n_above,
            "top_3": available_at_pos[:3],
            "scarcity_level": (
                "CRITICAL" if n_above <= critical_threshold
                else "TIGHT" if n_above <= tight_threshold
                else "MODERATE" if n_above <= 10
                else "DEEP"
            ),
        }

    return scarcity


# ── Player Projections ─────────────────────────────────────────────

def get_player_projection(player_name, scoring_format="ppr"):
    """Get full projection for a single player."""
    df = _load_predictions(scoring_format)
    if df is None:
        return {"error": "Model data not available."}
    row = _find_player(df, player_name)
    if row is None:
        return {"error": f"Player '{player_name}' not found."}
    return {
        "player_name": row["player_name"],
        "position": row["position"],
        "team": row.get("team", ""),
        "projected_ppg": round(float(row["predicted_ppg_2026"]), 2),
        "vbd": round(float(row["vbd"]), 2),
        "rank": int(row["rank"]),
        "ridge_pred": round(float(row["ridge_pred"]), 2),
        "xgb_pred": round(float(row["xgb_pred"]), 2),
    }


def compare_players(player_names, scoring_format="ppr"):
    """Compare projections for multiple players."""
    return [get_player_projection(name, scoring_format) for name in player_names]
