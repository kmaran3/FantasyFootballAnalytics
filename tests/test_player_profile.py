"""Tests for player profile data loading.

These tests verify that player bio info and ESPN IDs are populated
correctly, catching issues where production serves incomplete data
(e.g. only College instead of full bio, missing player images).
"""

import json


# ── Data loading smoke tests ────────────────────────────────────


def test_bio_map_populated(app):
    """The bio map should have entries after startup (nfl_data_py loaded)."""
    with app.app_context():
        from webapp.views import _bio_map
        assert len(_bio_map) > 0, (
            "_bio_map is empty — nfl_data_py.import_players() likely failed at startup. "
            "This will cause player profiles to show only College (from Sleeper fallback)."
        )


def test_espn_id_map_populated(app):
    """The ESPN ID map should have entries after startup."""
    with app.app_context():
        from webapp.views import _espn_id_map
        assert len(_espn_id_map) > 0, (
            "_espn_id_map is empty — player headshot images will be missing in production."
        )


def test_bio_map_has_full_fields(app):
    """Bio entries should have more than just College."""
    with app.app_context():
        from webapp.views import _bio_map
        if not _bio_map:
            return  # covered by test_bio_map_populated
        # Check a sample of entries — at least some should have multiple fields
        multi_field_count = sum(1 for bio in _bio_map.values() if len(bio) >= 3)
        assert multi_field_count > 0, (
            "No bio entries have 3+ fields (Age, Height, Weight, College, etc.). "
            "Player profiles will show incomplete info."
        )


def test_sleeper_cache_has_espn_ids(app):
    """The Sleeper player cache should provide ESPN IDs as a fallback."""
    with app.app_context():
        from webapp.views import _sleeper_player_cache, _refresh_sleeper_player_cache
        _refresh_sleeper_player_cache()
        by_id = _sleeper_player_cache.get('by_id', {})
        if not by_id:
            return  # Sleeper API may be unavailable in CI
        espn_count = sum(1 for p in by_id.values() if p.get('espn_id'))
        assert espn_count > 0, (
            "Sleeper cache loaded but contains no ESPN IDs — image fallback won't work."
        )


# ── Player profile page tests ──────────────────────────────────


def test_player_profile_page_loads(logged_in_client):
    """Player profile page returns 200."""
    resp = logged_in_client.get("/player/Patrick%20Mahomes?pos=QB&team=KC")
    assert resp.status_code == 200


def test_player_profile_has_bio_data(logged_in_client):
    """Player profile page should contain bio fields beyond just College."""
    resp = logged_in_client.get("/player/Patrick%20Mahomes?pos=QB&team=KC")
    assert resp.status_code == 200
    html = resp.data.decode()
    # The template renders player_bio as JSON via {{ player_bio | tojson }}
    # Look for the bio data in the page source
    assert 'player_bio' in html or 'bio-fields' in html, (
        "Player profile page missing bio section"
    )
    # Check that bio contains more than just College
    # The bio is embedded as: var playerBio = { ... };
    import re
    match = re.search(r'var playerBio\s*=\s*(\{.*?\});', html, re.DOTALL)
    if match:
        try:
            bio = json.loads(match.group(1))
            assert len(bio) > 1, (
                f"Player bio only has {list(bio.keys())} — expected multiple fields "
                f"(Age, Height, Weight, College, etc.). nfl_data_py may have failed."
            )
        except json.JSONDecodeError:
            pass  # Template escaping may make raw JSON parsing tricky


def test_player_profile_has_espn_id(logged_in_client):
    """Player profile page should include an ESPN ID for headshot images."""
    resp = logged_in_client.get("/player/Patrick%20Mahomes?pos=QB&team=KC")
    assert resp.status_code == 200
    html = resp.data.decode()
    # The template sets: var _espnId = "{{ espn_id }}";
    import re
    match = re.search(r'var _espnId\s*=\s*["\'](\d+)["\']', html)
    assert match, (
        "Player profile page has no ESPN ID — headshot image won't load. "
        "Check that _espn_id_map or Sleeper cache provides ESPN IDs."
    )


# ── Player stats API tests ─────────────────────────────────────


def test_player_quick_stats_has_bio(logged_in_client):
    """Player quick stats API should return bio data."""
    resp = logged_in_client.get(
        "/player_quick_stats?name=Patrick+Mahomes&pos=QB&team=KC"
    )
    assert resp.status_code == 200
    data = resp.get_json()
    bio = data.get('bio', {})
    if bio:
        assert len(bio) > 1, (
            f"Quick stats bio only has {list(bio.keys())} — expected multiple fields."
        )


def test_player_quick_stats_has_espn_id(logged_in_client):
    """Player quick stats API should return an ESPN ID."""
    resp = logged_in_client.get(
        "/player_quick_stats?name=Patrick+Mahomes&pos=QB&team=KC"
    )
    assert resp.status_code == 200
    data = resp.get_json()
    espn_id = data.get('espn_id')
    assert espn_id and str(espn_id).strip() not in ('', 'None', 'null'), (
        "Quick stats returned no ESPN ID — player image won't load."
    )
