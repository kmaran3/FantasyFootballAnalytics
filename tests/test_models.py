"""Tests for database models: creation, validation, relationships.

Post-Supabase migration: User model no longer has set_password/check_password.
User.id is a UUID string (not username). Tests validate model structure and FK relationships.
"""

from webapp import db, User, UserRanking, MockDraft, SavedLeague, DraftBoardSession
import json


def test_create_user(app):
    """User model creates with UUID id and email."""
    with app.app_context():
        u = User(id="uuid-model-test", email="model@test.com")
        db.session.add(u)
        db.session.commit()

        fetched = User.query.get("uuid-model-test")
        assert fetched is not None
        assert fetched.email == "model@test.com"
        assert fetched.id == "uuid-model-test"

        # Cleanup
        db.session.delete(fetched)
        db.session.commit()


def test_user_email_unique(app):
    """Duplicate emails raise IntegrityError."""
    import sqlalchemy
    with app.app_context():
        u1 = User(id="uuid-uniq-1", email="same@test.com")
        db.session.add(u1)
        db.session.commit()

        u2 = User(id="uuid-uniq-2", email="same@test.com")
        db.session.add(u2)
        try:
            db.session.commit()
            assert False, "Should have raised IntegrityError"
        except sqlalchemy.exc.IntegrityError:
            db.session.rollback()

        # Cleanup
        db.session.delete(u1)
        db.session.commit()


def test_user_ranking_relationship(app):
    """UserRanking links to User via foreign key."""
    with app.app_context():
        u = User(id="uuid-rankrel", email="rankrel@test.com")
        db.session.add(u)
        db.session.commit()

        r = UserRanking(
            user_id="uuid-rankrel",
            name="My PPR",
            ranking_type="PPR",
            ranking_data=json.dumps([{"name": "Player 1"}]),
        )
        db.session.add(r)
        db.session.commit()

        assert len(u.rankings) == 1
        assert u.rankings[0].name == "My PPR"

        # Cleanup
        db.session.delete(r)
        db.session.delete(u)
        db.session.commit()


def test_mock_draft_model(app):
    """MockDraft stores JSON board data."""
    with app.app_context():
        u = User(id="uuid-draftmodel", email="draft@model.com")
        db.session.add(u)
        db.session.commit()

        md = MockDraft(
            user_id="uuid-draftmodel",
            draft_type="snake",
            scoring="ppr",
            settings=json.dumps({"numTeams": 12}),
            board=json.dumps([["pick1", "pick2"]]),
            user_team=json.dumps(["pick1"]),
        )
        db.session.add(md)
        db.session.commit()

        fetched = MockDraft.query.filter_by(user_id="uuid-draftmodel").first()
        assert fetched is not None
        assert json.loads(fetched.settings)["numTeams"] == 12

        # Cleanup
        db.session.delete(fetched)
        db.session.delete(u)
        db.session.commit()


def test_saved_league_unique_constraint(app):
    """Duplicate (user_id, league_id) raises IntegrityError."""
    import sqlalchemy
    with app.app_context():
        u = User(id="uuid-uniquetest", email="unique@test.com")
        db.session.add(u)
        db.session.commit()

        lg1 = SavedLeague(user_id="uuid-uniquetest", league_id="lg-dup", league_name="First")
        db.session.add(lg1)
        db.session.commit()

        lg2 = SavedLeague(user_id="uuid-uniquetest", league_id="lg-dup", league_name="Second")
        db.session.add(lg2)
        try:
            db.session.commit()
            assert False, "Should have raised IntegrityError"
        except sqlalchemy.exc.IntegrityError:
            db.session.rollback()

        # Cleanup
        db.session.delete(lg1)
        db.session.delete(u)
        db.session.commit()


def test_draft_board_session_model(app):
    """DraftBoardSession stores settings and state JSON."""
    with app.app_context():
        u = User(id="uuid-sesstest", email="sess@test.com")
        db.session.add(u)
        db.session.commit()

        sess = DraftBoardSession(
            user_id="uuid-sesstest",
            source="sleeper",
            league_id="lg-123",
            draft_id="dr-456",
            settings=json.dumps({"numTeams": 12}),
            state=json.dumps({"board": [], "currentPickNo": 5}),
            last_pick=5,
        )
        db.session.add(sess)
        db.session.commit()

        fetched = DraftBoardSession.query.filter_by(user_id="uuid-sesstest").first()
        assert fetched is not None
        assert fetched.source == "sleeper"
        assert fetched.last_pick == 5
        assert json.loads(fetched.state)["currentPickNo"] == 5

        # Cleanup
        db.session.delete(fetched)
        db.session.delete(u)
        db.session.commit()
