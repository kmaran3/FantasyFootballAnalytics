"""Tests for the rankings player-context badges."""

from webapp import views


def test_injury_and_rookie_flags_use_sleeper_status(monkeypatch):
    monkeypatch.setattr(
        views,
        "_get_sleeper_player_update",
        lambda *args: {
            "status": "OUT",
            "injury_status": "Out",
            "summary": "Out - Knee",
            "title": "Out - Knee | Updated Aug 07",
            "tone": "danger",
        },
    )
    monkeypatch.setattr(views, "_rookie_names", {"rookie player"})

    flags = views._build_rankings_flags("Rookie Player", "RB", "NYG", {})

    assert [flag["label"] for flag in flags] == ["Injury", "Rookie"]
    assert flags[0]["tone"] == "danger"
    assert flags[0]["description"] == "Out - Knee | Updated Aug 07"
    assert "Off-field" not in {flag["label"] for flag in flags}


def test_rankings_flags_preserve_live_team_change_detection(monkeypatch):
    monkeypatch.setattr(views, "_sleeper_team_map", {"moved player": "NE"})
    monkeypatch.setattr(views, "_latest_player_team_map", lambda: {"moved player": "DAL"})
    monkeypatch.setattr(views, "_get_sleeper_player_update", lambda *args: {})
    monkeypatch.setattr(views, "_fetch_player_move_news", lambda *args: {})
    monkeypatch.setattr(views, "_rookie_names", set())

    row = {"Name": "Moved Player", "Position": "WR", "Team": "DAL"}
    enriched = views._inject_rankings_flags([row])

    assert enriched[0]["Team"] == "NE"
    assert [flag["label"] for flag in enriched[0]["Flags"]] == ["New Team"]
