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


def test_github_install_url_requires_config(github_app_config):
    github_app_config["install_url"] = ""
    service = GitHubAppService(GitHubAppConfig.from_config({"GITHUB_APP": github_app_config}))
    with pytest.raises(Exception) as exc:
        service.build_installation_url("/git/HTAN_INT")
    assert "installation URL is not configured" in str(exc.value)


def test_github_install_url_appends_state(github_app_config):
    github_app_config["install_url"] = "https://github.com/apps/calypr-github/installations/new"
    service = GitHubAppService(GitHubAppConfig.from_config({"GITHUB_APP": github_app_config}))
    install_url = service.build_installation_url("/git/HTAN_INT")
    assert install_url == "https://github.com/apps/calypr-github/installations/new?state=%2Fgit%2FHTAN_INT"


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


@responses.activate
def test_github_installation_status_success(
    client, encoded_creds_jwt, mock_arborist_requests
):
    mock_arborist_requests({"arborist/auth/request": {"POST": ({"auth": True}, 200)}})
    responses.add(
        responses.GET,
        "https://api.github.example/repos/HTAN_INT/BForePC/installation",
        json={
            "id": 42,
            "target_type": "Organization",
            "html_url": "https://github.com/organizations/HTAN_INT/settings/installations/42",
            "account": {"login": "HTAN_INT"},
        },
        status=200,
    )

    response = client.post(
        "/credentials/github/installation",
        json={"owner": "HTAN_INT", "repo": "BForePC"},
        headers={"Authorization": "Bearer " + encoded_creds_jwt["jwt"]},
    )

    assert response.status_code == 200
    assert response.json == {
        "installed": True,
        "repository": {"owner": "HTAN_INT", "repo": "BForePC"},
        "installation_id": 42,
        "target": "HTAN_INT",
        "target_type": "Organization",
        "html_url": "https://github.com/organizations/HTAN_INT/settings/installations/42",
        "repository_selection": None,
    }


@responses.activate
def test_github_installation_status_not_found(
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
        "/credentials/github/installation",
        json={"owner": "HTAN_INT", "repo": "BForePC"},
        headers={"Authorization": "Bearer " + encoded_creds_jwt["jwt"]},
    )

    assert response.status_code == 200
    assert response.json == {
        "installed": False,
        "repository": {"owner": "HTAN_INT", "repo": "BForePC"},
    }


@responses.activate


@responses.activate
def test_github_organization_installation_success(
    client, encoded_creds_jwt, mock_arborist_requests
):
    mock_arborist_requests({"arborist/auth/request": {"POST": ({"auth": True}, 200)}})
    responses.add(
        responses.GET,
        "https://api.github.example/orgs/HTAN_INT/installation",
        json={
            "id": 42,
            "target_type": "Organization",
            "repository_selection": "selected",
            "html_url": "https://github.com/organizations/HTAN_INT/settings/installations/42",
            "account": {"login": "HTAN_INT"},
        },
        status=200,
    )

    response = client.post(
        "/credentials/github/organization-installation",
        json={"owner": "HTAN_INT"},
        headers={"Authorization": "Bearer " + encoded_creds_jwt["jwt"]},
    )

    assert response.status_code == 200
    assert response.json == {
        "installed": True,
        "organization": "HTAN_INT",
        "installation_id": 42,
        "target": "HTAN_INT",
        "target_type": "Organization",
        "html_url": "https://github.com/organizations/HTAN_INT/settings/installations/42",
        "repository_selection": "selected",
    }


@responses.activate
def test_github_organization_installation_not_found(
    client, encoded_creds_jwt, mock_arborist_requests
):
    mock_arborist_requests({"arborist/auth/request": {"POST": ({"auth": True}, 200)}})
    responses.add(
        responses.GET,
        "https://api.github.example/orgs/HTAN_INT/installation",
        json={"message": "Not Found"},
        status=404,
    )

    response = client.post(
        "/credentials/github/organization-installation",
        json={"owner": "HTAN_INT"},
        headers={"Authorization": "Bearer " + encoded_creds_jwt["jwt"]},
    )

    assert response.status_code == 200
    assert response.json == {
        "installed": False,
        "organization": "HTAN_INT",
    }


def test_github_organization_installation_requires_authz(
    client, encoded_creds_jwt, mock_arborist_requests
):
    mock_arborist_requests({"arborist/auth/request": {"POST": ({"auth": False}, 200)}})

    response = client.post(
        "/credentials/github/organization-installation",
        json={"owner": "HTAN_INT"},
        headers={"Authorization": "Bearer " + encoded_creds_jwt["jwt"]},
    )

    assert response.status_code == 403


def test_github_installation_url_success(
    client, encoded_creds_jwt, mock_arborist_requests
):
    mock_arborist_requests({"arborist/auth/request": {"POST": ({"auth": True}, 200)}})

    response = client.post(
        "/credentials/github/install-url",
        json={"owner": "HTAN_INT", "redirect_path": "/git/HTAN_INT"},
        headers={"Authorization": "Bearer " + encoded_creds_jwt["jwt"]},
    )

    assert response.status_code == 200
    assert response.json == {
        "install_url": "https://github.com/apps/calypr-github/installations/new?state=%2Fgit%2FHTAN_INT",
        "owner": "HTAN_INT",
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


def test_github_installation_url_requires_authz(
    client, encoded_creds_jwt, mock_arborist_requests
):
    mock_arborist_requests({"arborist/auth/request": {"POST": ({"auth": False}, 200)}})

    response = client.post(
        "/credentials/github/install-url",
        json={"owner": "HTAN_INT", "redirect_path": "/git/HTAN_INT"},
        headers={"Authorization": "Bearer " + encoded_creds_jwt["jwt"]},
    )

    assert response.status_code == 403


def test_github_installation_token_requires_authorization(client):
    response = client.post(
        "/credentials/github/token", json={"owner": "HTAN_INT", "repo": "BForePC"}
    )
    assert response.status_code == 401


def test_github_installation_status_requires_authorization(client):
    response = client.post(
        "/credentials/github/installation", json={"owner": "HTAN_INT", "repo": "BForePC"}
    )
    assert response.status_code == 401


def test_github_installation_url_requires_authorization(client):
    response = client.post(
        "/credentials/github/install-url", json={"owner": "HTAN_INT"}
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

def test_github_organization_installation_requires_authorization(client):
    response = client.post(
        "/credentials/github/organization-installation", json={"owner": "HTAN_INT"}
    )
    assert response.status_code == 401
