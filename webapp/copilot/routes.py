"""Copilot SSE endpoint — streams AI draft recommendations."""

import json
import os
import time

from flask import request, Response, stream_with_context, jsonify
from flask_login import login_required, current_user

from . import copilot_bp
from .copilot_tools import (
    analyze_roster,
    get_best_value_picks,
    get_positional_scarcity,
)
from .prompt_builder import build_prompt, build_fallback_response

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# In-memory rate limiter: user_id -> [timestamps]
_rate_limits = {}


def _sse(event_type, **kwargs):
    """Format a single SSE data line."""
    payload = {"type": event_type, **kwargs}
    return f"data: {json.dumps(payload)}\n\n"


def _best_available_from_value(value_picks, needs=None):
    """Extract best available player info for the BAV bar."""
    if not value_picks:
        return None

    target = None
    if needs:
        needed_positions = {n["position"] for n in needs}
        for vp in value_picks:
            if vp["position"] in needed_positions:
                target = vp
                break
    if not target:
        target = value_picks[0]

    reason = target.get("assessment", "Best Available")
    if needs:
        for n in needs:
            if n["position"] == target["position"]:
                reason = n["note"]
                break

    return {
        "name": target["player_name"],
        "position": target["position"],
        "ppg": target["projected_ppg"],
        "reason": reason,
    }


@copilot_bp.route("/draft-board/copilot/chat", methods=["POST"])
@login_required
def copilot_chat():
    user_id = current_user.id

    # Rate limit: 10 requests/minute
    now = time.time()
    timestamps = _rate_limits.get(user_id, [])
    timestamps = [t for t in timestamps if now - t < 60]
    if len(timestamps) >= 10:
        return jsonify(
            error="You're sending messages too quickly. Please wait a moment."
        ), 429
    timestamps.append(now)
    _rate_limits[user_id] = timestamps

    data = request.get_json(silent=True)
    if not data:
        return jsonify(error="Invalid request."), 400

    message = (data.get("message") or "").strip()
    context = data.get("context", {})

    if not message:
        return jsonify(error="Message is required."), 400
    if len(message) > 2000:
        return jsonify(error="Message must be under 2000 characters."), 400

    # Run tool functions synchronously (~50-100ms)
    user_roster = context.get("user_roster", [])
    roster_slots = context.get("roster_slots", {})
    scoring = context.get("scoring_format", "ppr")
    num_teams = context.get("num_teams", 12)
    available = context.get("available_players", [])
    current_pick = context.get("current_pick", 1)

    roster_analysis = analyze_roster(user_roster, roster_slots, scoring, num_teams)
    value_picks = get_best_value_picks(
        available, current_pick, num_teams, scoring
    )
    scarcity = get_positional_scarcity(available, scoring, num_teams)

    needs = roster_analysis.get("positional_needs", [])
    bav = _best_available_from_value(value_picks, needs)

    # Check for API key — fallback if missing
    api_key = GROQ_API_KEY or os.environ.get("GROQ_API_KEY")
    if not api_key:
        fallback = build_fallback_response(context, roster_analysis, value_picks)
        return Response(
            _sse("done", text=fallback, best_available=bav),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Build prompt
    prompt = build_prompt(message, context, roster_analysis, value_picks, scarcity)

    def generate():
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=api_key,
                base_url="https://api.groq.com/openai/v1",
            )
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=prompt,
                stream=True,
                max_tokens=1024,
            )
            for chunk in response:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield _sse("chunk", text=delta.content)
            yield _sse("done", best_available=bav)
        except Exception:
            fallback = build_fallback_response(context, roster_analysis, value_picks)
            yield _sse("error", fallback=fallback, best_available=bav)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@copilot_bp.route("/draft-board/copilot/status", methods=["GET"])
@login_required
def copilot_status():
    """Check if the copilot is available (API key configured)."""
    api_key = GROQ_API_KEY or os.environ.get("GROQ_API_KEY")
    return jsonify(available=bool(api_key))
