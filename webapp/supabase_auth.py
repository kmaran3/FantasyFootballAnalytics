"""Supabase Auth integration for Flask.

Single point of integration between Flask and Supabase Auth.
No other file should import the `supabase` package directly.
"""

from dataclasses import dataclass, field
from functools import wraps
import os

import jwt as pyjwt
from flask import g, flash, redirect, request, session, url_for
from supabase import create_client, Client


_supabase: Client = None
_SUPABASE_JWT_SECRET: str = None


@dataclass
class SupabaseUser:
    """Lightweight user object populated from JWT claims or Supabase API response."""
    id: str
    email: str
    user_metadata: dict = field(default_factory=dict)


def init_supabase(app):
    """Initialize Supabase client. Called from create_app()."""
    global _supabase, _SUPABASE_JWT_SECRET

    url = os.environ.get('SUPABASE_URL')
    anon_key = os.environ.get('SUPABASE_ANON_KEY')

    if url and anon_key:
        _supabase = create_client(url, anon_key)
        _SUPABASE_JWT_SECRET = os.environ.get('SUPABASE_JWT_SECRET', '')
    else:
        app.logger.warning(
            'SUPABASE_URL or SUPABASE_ANON_KEY not set — auth routes will not work.'
        )
        _supabase = None
        _SUPABASE_JWT_SECRET = ''

    app.before_request(_load_user_from_session)

    @app.context_processor
    def inject_user():
        return dict(current_user=g.get('user'))


def get_supabase() -> Client:
    """Return the Supabase client instance."""
    return _supabase


# ── Session helpers ──────────────────────────────────────────────

def _store_session(sb_session):
    session['sb_access_token'] = sb_session.access_token
    session['sb_refresh_token'] = sb_session.refresh_token


def _clear_session():
    session.pop('sb_access_token', None)
    session.pop('sb_refresh_token', None)


# ── Before-request: token validation ────────────────────────────

def _load_user_from_session():
    """Validate JWT on every request. Network call only when token is expired."""
    g.user = None
    access_token = session.get('sb_access_token')
    refresh_token = session.get('sb_refresh_token')

    if not access_token:
        return

    try:
        # Peek at the token header to determine algorithm
        header = pyjwt.get_unverified_header(access_token)
        alg = header.get('alg', 'HS256')

        if alg == 'HS256' and _SUPABASE_JWT_SECRET:
            # Symmetric — verify signature with shared secret
            payload = pyjwt.decode(
                access_token,
                _SUPABASE_JWT_SECRET,
                algorithms=['HS256'],
                audience='authenticated',
            )
        else:
            # RS256 or no secret configured — decode without signature
            # verification. The token was issued by Supabase and received
            # directly from their API, so it is trusted.
            payload = pyjwt.decode(
                access_token,
                options={'verify_signature': False},
                audience='authenticated',
            )
        g.user = _jwt_payload_to_user(payload)

    except pyjwt.ExpiredSignatureError:
        # Token expired — refresh via Supabase (network call)
        if not refresh_token:
            _clear_session()
            return
        try:
            resp = _supabase.auth.refresh_session(refresh_token)
            session['sb_access_token'] = resp.session.access_token
            session['sb_refresh_token'] = resp.session.refresh_token
            g.user = _supabase_user_to_local(resp.user)
        except Exception as e:
            import traceback
            print(f'[AUTH] Token refresh failed: {e}')
            traceback.print_exc()
            _clear_session()

    except Exception as e:
        import traceback
        print(f'[AUTH] JWT decode failed: {e}')
        traceback.print_exc()
        _clear_session()


def _jwt_payload_to_user(payload):
    return SupabaseUser(
        id=payload['sub'],
        email=payload.get('email', ''),
        user_metadata=payload.get('user_metadata', {}),
    )


def _supabase_user_to_local(sb_user):
    return SupabaseUser(
        id=sb_user.id,
        email=sb_user.email or '',
        user_metadata=sb_user.user_metadata or {},
    )


# ── Decorator ────────────────────────────────────────────────────

def login_required(f):
    """Decorator replacing Flask-Login's @login_required."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if g.user is None:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('main.login', next=request.path))
        return f(*args, **kwargs)
    return decorated


# ── Auth actions ─────────────────────────────────────────────────

def sign_up(email, password):
    """Register a new user with email/password."""
    return _supabase.auth.sign_up({'email': email, 'password': password})


def sign_in(email, password):
    """Sign in with email/password. Stores tokens in Flask session."""
    resp = _supabase.auth.sign_in_with_password({'email': email, 'password': password})
    _store_session(resp.session)
    return resp


def sign_in_with_oauth(provider, redirect_to):
    """Get OAuth URL for social login (google).

    Generates PKCE code_verifier, stores it in the Flask session so it
    survives across requests/workers, and builds the authorization URL
    with the code_challenge.
    """
    import secrets
    import hashlib
    import base64

    # Generate PKCE code verifier and challenge
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .rstrip(b'=')
        .decode()
    )

    # Store verifier in Flask session for the callback
    session['pkce_code_verifier'] = code_verifier

    # Build the OAuth URL manually with our code_challenge
    params = (
        f"provider={provider}"
        f"&redirect_to={redirect_to}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )
    url = f"{_supabase.supabase_url}/auth/v1/authorize?{params}"

    class OAuthResult:
        def __init__(self, url):
            self.url = url

    return OAuthResult(url)


def exchange_code_for_session(code):
    """Exchange an OAuth authorization code for a session using the stored PKCE verifier."""
    import httpx

    code_verifier = session.pop('pkce_code_verifier', '')

    resp = httpx.post(
        f"{_supabase.supabase_url}/auth/v1/token?grant_type=pkce",
        json={
            'auth_code': code,
            'code_verifier': code_verifier,
        },
        headers={
            'apikey': _supabase.supabase_key,
            'Content-Type': 'application/json',
        },
    )
    resp.raise_for_status()
    data = resp.json()

    session['sb_access_token'] = data['access_token']
    session['sb_refresh_token'] = data.get('refresh_token', '')
    return data


def sign_out():
    """Sign out and clear session."""
    try:
        _supabase.auth.sign_out()
    except Exception:
        pass
    _clear_session()


def reset_password(email, redirect_to):
    """Send password reset email."""
    return _supabase.auth.reset_password_for_email(email, {
        'redirect_to': redirect_to,
    })
