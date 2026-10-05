from types import SimpleNamespace

import flask
import pytest

from fence import reject_login_without_project_access
from fence.auth import has_project_read_or_write
from fence.config import config


@pytest.mark.parametrize(
    "mapping,expected",
    [
        ({}, False),
        ({"/programs/a/projects/p": []}, False),
        ({"/programs/a/projects/p": [{"service": "arborist", "method": "read"}]}, True),
        ({"/programs/a/projects/p": [{"method": "read"}]}, True),
        ({"/programs/a/projects/p": ["read"]}, True),
        ({"/programs/a/projects/p": [{"service": "*", "method": "write"}]}, True),
        ({"/programs/a/projects/p": [{"service": "arborist", "method": "*"}]}, True),
        (
            {"/programs/a/projects/p": [{"service": "arborist", "method": "delete"}]},
            False,
        ),
        (
            {
                "/programs/a/projects": [
                    {"service": "arborist", "method": "create-descendant"}
                ]
            },
            False,
        ),
        ({"/programs/a/projects/p": [{"service": "other", "method": "read"}]}, False),
    ],
)
def test_project_access_predicate(mapping, expected):
    assert has_project_read_or_write(mapping) is expected


def test_login_gate_rejects_without_project_access(monkeypatch):
    monkeypatch.setitem(config, "REQUIRE_PROJECT_ACCESS_ON_LOGIN", True)
    app = flask.Flask(__name__)
    app.secret_key = "test-only"
    app.arborist = SimpleNamespace(auth_mapping=lambda username: {})

    with app.test_request_context("/login/callback"):
        flask.session["username"] = "user@example.org"
        flask.g.new_login_username = "user@example.org"
        response = reject_login_without_project_access(flask.make_response("welcome"))
        assert response.status_code == 403
        assert response.get_json() == {"error": "No project access"}
        assert not flask.session


def test_browser_login_returns_to_frontend_without_a_session(monkeypatch):
    monkeypatch.setitem(config, "REQUIRE_PROJECT_ACCESS_ON_LOGIN", True)
    monkeypatch.setitem(config, "ROOT_URL", "https://calypr.example.org")
    app = flask.Flask("fence")
    app.secret_key = "test-only"
    app.arborist = SimpleNamespace(auth_mapping=lambda username: {})

    with app.test_request_context(
        "/login/google/login/", headers={"Accept": "text/html"}
    ):
        flask.session["username"] = "user@example.org"
        flask.g.new_login_username = "user@example.org"
        response = reject_login_without_project_access(flask.make_response("welcome"))
        assert response.status_code == 303
        assert response.location == (
            "https://calypr.example.org/?login_error=no_project_access"
        )
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert not flask.session


def test_login_gate_accepts_a_project_read_grant(monkeypatch):
    monkeypatch.setitem(config, "REQUIRE_PROJECT_ACCESS_ON_LOGIN", True)
    app = flask.Flask(__name__)
    app.secret_key = "test-only"
    app.arborist = SimpleNamespace(
        auth_mapping=lambda username: {
            "/programs/a/projects/p": [{"service": "arborist", "method": "read"}]
        }
    )

    with app.test_request_context("/login/callback"):
        flask.session["username"] = "user@example.org"
        flask.g.new_login_username = "user@example.org"
        response = reject_login_without_project_access(flask.make_response("welcome"))
        assert response.status_code == 200
        assert flask.session["username"] == "user@example.org"


def test_login_gate_fails_closed_when_arborist_unavailable(monkeypatch):
    monkeypatch.setitem(config, "REQUIRE_PROJECT_ACCESS_ON_LOGIN", True)
    app = flask.Flask(__name__)
    app.secret_key = "test-only"
    app.arborist = None

    with app.test_request_context("/login/callback"):
        flask.session["username"] = "user@example.org"
        flask.g.new_login_username = "user@example.org"
        response = reject_login_without_project_access(flask.make_response("welcome"))
        assert response.status_code == 503
        assert not flask.session


def test_login_gate_does_not_recheck_an_existing_session(monkeypatch):
    monkeypatch.setitem(config, "REQUIRE_PROJECT_ACCESS_ON_LOGIN", True)
    app = flask.Flask(__name__)
    app.secret_key = "test-only"
    app.arborist = SimpleNamespace(auth_mapping=lambda username: {})

    with app.test_request_context("/user/"):
        flask.session["username"] = "user@example.org"
        response = reject_login_without_project_access(flask.make_response("user info"))
        assert response.status_code == 200
        assert flask.session["username"] == "user@example.org"


def test_login_gate_rejects_when_arborist_raises(monkeypatch):
    monkeypatch.setitem(config, "REQUIRE_PROJECT_ACCESS_ON_LOGIN", True)
    app = flask.Flask(__name__)
    app.secret_key = "test-only"

    def fail(_username):
        raise TimeoutError("Arborist unavailable")

    app.arborist = SimpleNamespace(auth_mapping=fail)
    with app.test_request_context("/login/callback"):
        flask.session["username"] = "user@example.org"
        flask.g.new_login_username = "user@example.org"
        response = reject_login_without_project_access(flask.make_response("welcome"))
        assert response.status_code == 503
        assert not flask.session
