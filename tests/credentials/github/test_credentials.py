import copy

import pytest
import responses

from fence.config import config
from fence.errors import UserError
from fence.resources.github_app.service import GitHubAppConfig, GitHubAppService


@pytest.fixture(autouse=True)
def mock_github_app_jwt(monkeypatch):
    monkeypatch.setattr(GitHubAppService, "_app_jwt", lambda self: "signed-jwt")


@pytest.fixture
def github_app_config():
    return copy.deepcopy(config.get("GITHUB_APP"))


def test_github_app_config_requires_app_id(github_app_config):
    github_app_config["app_id"] = ""
    with pytest.raises(UserError):
        GitHubAppConfig.from_config({"GITHUB_APP": github_app_config})


def test_github_app_config_requires_key_material(github_app_config):
    github_app_config["private_key"] = ""
    github_app_config["private_key_file"] = ""
    with pytest.raises(UserError):
        GitHubAppConfig.from_config({"GITHUB_APP": github_app_config})


@responses.activate
def test_github_installation_token_success(
    client, encoded_creds_jwt, mock_arborist_requests
):
    mock_arborist_requests({"arborist/auth/request": {"POST": ({"auth": True}, 200)}})
    responses.add(
        responses.GET,
        "https://api.github.example/repos/HTAN_INT/BForePC/installation",
        json={"id": 42},
        status=200,
    )
    responses.add(
        responses.POST,
        "https://api.github.example/app/installations/42/access_tokens",
        json={"token": "ghs_test", "expires_at": "2026-05-20T18:00:00Z"},
        status=201,
    )

    response = client.post(
        "/credentials/github/token",
        json={"owner": "HTAN_INT", "repo": "BForePC"},
        headers={"Authorization": "Bearer " + encoded_creds_jwt["jwt"]},
    )

    assert response.status_code == 200
    assert response.json == {
        "token": "ghs_test",
        "expires_at": "2026-05-20T18:00:00Z",
        "repository": {"owner": "HTAN_INT", "repo": "BForePC"},
    }


def test_github_installation_token_requires_authz(
    client, encoded_creds_jwt, mock_arborist_requests
):
    mock_arborist_requests({"arborist/auth/request": {"POST": ({"auth": False}, 200)}})

    response = client.post(
        "/credentials/github/token",
        json={"owner": "HTAN_INT", "repo": "BForePC"},
        headers={"Authorization": "Bearer " + encoded_creds_jwt["jwt"]},
    )

    assert response.status_code == 403


def test_github_installation_token_requires_authorization(client):
    response = client.post(
        "/credentials/github/token", json={"owner": "HTAN_INT", "repo": "BForePC"}
    )
    assert response.status_code == 401


@responses.activate
def test_github_installation_token_not_found(
    client, encoded_creds_jwt, mock_arborist_requests
):
    mock_arborist_requests({"arborist/auth/request": {"POST": ({"auth": True}, 200)}})
    responses.add(
        responses.GET,
        "https://api.github.example/repos/HTAN_INT/BForePC/installation",
        json={"message": "Not Found"},
        status=404,
    )

    response = client.post(
        "/credentials/github/token",
        json={"owner": "HTAN_INT", "repo": "BForePC"},
        headers={"Authorization": "Bearer " + encoded_creds_jwt["jwt"]},
    )

    assert response.status_code == 404


@responses.activate
def test_github_installation_token_upstream_failure(
    client, encoded_creds_jwt, mock_arborist_requests
):
    mock_arborist_requests({"arborist/auth/request": {"POST": ({"auth": True}, 200)}})
    responses.add(
        responses.GET,
        "https://api.github.example/repos/HTAN_INT/BForePC/installation",
        json={"message": "server error"},
        status=500,
    )

    response = client.post(
        "/credentials/github/token",
        json={"owner": "HTAN_INT", "repo": "BForePC"},
        headers={"Authorization": "Bearer " + encoded_creds_jwt["jwt"]},
    )

    assert response.status_code == 502
