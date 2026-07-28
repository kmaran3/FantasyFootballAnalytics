"""Builds the LLM prompt from draft context and pre-computed tool outputs."""

SYSTEM_PROMPT = """\
You are the Draft Copilot for a fantasy football draft board. You help users
make optimal draft picks based on their roster needs, available players, and
league settings.

You have been given pre-computed analysis from specialist tools:
- ROSTER ANALYSIS: positional gaps and bye week conflicts
- VALUE ANALYSIS: best value picks relative to current draft position
- SCARCITY ANALYSIS: how many startable players remain at each position
- PROJECTIONS: ML model predictions (PPG, VBD) for top candidates

Use this analysis to provide:
1. **#1 Recommended pick** with clear reasoning
2. **2-3 alternatives** with brief rationale
3. **Risk note** if any (injury, rookie uncertainty, model disagreement)

Rules:
- Only recommend players from the AVAILABLE PLAYERS list below
- Never recommend a position that exceeds roster limits
- Always acknowledge positional need before recommending
- Factor in scoring format (PPR/half-PPR/standard) and league size
- Flag rookies or low-confidence projections
- Be concise — this is a live draft, the user needs quick answers
- Format your response with markdown (bold names, bullet lists)
"""


def build_prompt(message, context, roster_analysis, value_picks, scarcity):
    """Build the full prompt from context + tool outputs.

    Returns a list of message dicts in OpenAI chat format (system + user).
    """
    num_teams = context.get("num_teams", 12)
    scoring = context.get("scoring_format", "ppr")
    league_type = context.get("league_type", "redraft")
    current_pick = context.get("current_pick", 1)
    user_slot = context.get("user_slot", "")
    roster_slots = context.get("roster_slots", {})
    user_roster = context.get("user_roster", [])
    available = context.get("available_players", [])

    # Format roster
    if user_roster:
        roster_str = "\n".join(
            f"- {p.get('name', '?')} ({p.get('position', '?')})"
            for p in user_roster
        )
    else:
        roster_str = "Empty — first pick"

    # Format roster slots
    slots_str = ", ".join(f"{k}: {v}" for k, v in roster_slots.items() if v)

    # Format roster analysis
    needs_lines = []
    for n in roster_analysis.get("positional_needs", []):
        needs_lines.append(
            f"- {n['position']}: {n['note']} (priority: {n['priority']})"
        )
    needs_str = "\n".join(needs_lines) if needs_lines else "All starter slots filled."

    bye_lines = []
    for bc in roster_analysis.get("bye_week_conflicts", []):
        bye_lines.append(
            f"- Week {bc['week']}: {', '.join(bc['players'])} ({bc['count']} players)"
        )
    bye_str = "\n".join(bye_lines) if bye_lines else "No bye week conflicts."

    summary = roster_analysis.get("roster_summary", {})
    picks_remaining = summary.get("picks_remaining", "?")

    # Format available players table
    avail_lines = []
    for i, p in enumerate(available[:30]):
        avail_lines.append(
            f"{i+1}. {p.get('name', '?')} | {p.get('position', '?')} | "
            f"{p.get('nfl_team', '')} | PPG: {p.get('ppg', '?')} | VBD: {p.get('vbd', '?')}"
        )
    avail_str = "\n".join(avail_lines) if avail_lines else "No players available — draft is complete."

    # Format value picks
    value_lines = []
    for vp in value_picks:
        value_lines.append(
            f"- {vp['player_name']} ({vp['position']}) — {vp['assessment']}, "
            f"VBD rank #{vp['vbd_rank']}, PPG: {vp['projected_ppg']}"
        )
    value_str = "\n".join(value_lines) if value_lines else "No value data available."

    # Format scarcity
    scarcity_lines = []
    for pos, data in scarcity.items():
        level = data.get("scarcity_level", "?")
        above = data.get("above_replacement", 0)
        scarcity_lines.append(f"- {pos}: {level} ({above} startable players remaining)")
        if level in ("CRITICAL", "TIGHT") and data.get("top_3"):
            for tp in data["top_3"]:
                scarcity_lines.append(
                    f"  → {tp['player_name']} (PPG: {tp['projected_ppg']})"
                )
    scarcity_str = "\n".join(scarcity_lines) if scarcity_lines else "No scarcity data."

    user_prompt = f"""\
LEAGUE: {num_teams}-team {scoring} {league_type}
ROSTER SLOTS: {slots_str}
MY PICK: #{current_pick}{f' (slot {user_slot})' if user_slot else ''}
PICKS REMAINING: {picks_remaining}

MY ROSTER:
{roster_str}

ROSTER ANALYSIS:
Positional needs:
{needs_str}

Bye week conflicts:
{bye_str}

AVAILABLE PLAYERS (top 30 by value):
{avail_str}

VALUE PICKS (best value at current pick):
{value_str}

POSITIONAL SCARCITY:
{scarcity_str}

USER QUESTION: {message}"""

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def build_fallback_response(context, roster_analysis, value_picks):
    """Build a rule-based markdown response when Gemini is unavailable."""
    needs = roster_analysis.get("positional_needs", [])
    available = context.get("available_players", [])

    lines = []

    # Find top target based on roster need
    top_target = None
    if value_picks:
        if needs:
            needed_positions = {n["position"] for n in needs}
            for vp in value_picks:
                if vp["position"] in needed_positions:
                    top_target = vp
                    break
        if not top_target:
            top_target = value_picks[0]

    if not top_target and available:
        p = available[0]
        top_target = {
            "player_name": p.get("name", "?"),
            "position": p.get("position", "?"),
            "projected_ppg": p.get("ppg", "?"),
            "assessment": "Best Available",
        }

    if top_target:
        lines.append(
            f"## Recommended: **{top_target['player_name']} "
            f"({top_target['position']})**"
        )
        lines.append(
            f"Projected PPG: {top_target.get('projected_ppg', '?')} — "
            f"{top_target.get('assessment', 'Best Available')}"
        )
    else:
        lines.append("The draft is complete — no more picks to make!")
        return "\n\n".join(lines)

    # Needs summary
    if needs:
        lines.append("\n**Your roster needs:**")
        for n in needs[:3]:
            lines.append(f"- {n['position']}: {n['note']}")

    # Alternatives
    alts = [vp for vp in value_picks if vp != top_target][:2]
    if alts:
        lines.append("\n**Alternatives:**")
        for a in alts:
            lines.append(
                f"- **{a['player_name']} ({a['position']})** — "
                f"PPG: {a['projected_ppg']}, {a['assessment']}"
            )

    lines.append(
        "\n*Running in limited mode — AI Copilot requires API key for full analysis.*"
    )

    return "\n".join(lines)
