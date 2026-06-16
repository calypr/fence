from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import jwt
import requests

from cdislogging import get_logger

from fence.errors import BadGatewayError, InternalError, NotFound, UnavailableError, UserError

logger = get_logger(__name__)

DEFAULT_GITHUB_API_BASE_URL = "https://api.github.com"
DEFAULT_GITHUB_TIMEOUT_SECONDS = 10
DEFAULT_GITHUB_READ_PERMISSIONS = {"contents": "read", "metadata": "read"}
DEFAULT_GITHUB_WRITE_PERMISSIONS = {
    "contents": "write",
    "metadata": "read",
    "pull_requests": "write",
}


@dataclass(frozen=True)
class GitHubAppConfig:
    app_id: str
    private_key: str
    api_base_url: str = DEFAULT_GITHUB_API_BASE_URL
    timeout_seconds: int = DEFAULT_GITHUB_TIMEOUT_SECONDS
    install_url: str = ""

    @classmethod
    def from_config(cls, config):
        github_app_config = config.get("GITHUB_APP")
        if not github_app_config:
            raise UnavailableError("GitHub App token brokering is not configured")

        app_id = str(github_app_config.get("app_id", "")).strip()
        private_key = str(github_app_config.get("private_key", "")).strip()
        private_key_file = str(github_app_config.get("private_key_file", "")).strip()
        if not app_id:
            raise UserError("GITHUB_APP.app_id must be configured")
        if private_key and private_key_file:
            raise UserError(
                "GITHUB_APP.private_key and GITHUB_APP.private_key_file are mutually exclusive"
            )
        if not private_key and not private_key_file:
            raise UserError(
                "one of GITHUB_APP.private_key or GITHUB_APP.private_key_file must be configured"
            )

        if private_key_file:
            try:
                private_key = Path(private_key_file).read_text()
            except OSError as exc:
                raise InternalError(
                    f"failed to read GitHub App private key file {private_key_file}: {exc}"
                )

        api_base_url = (
            str(
                github_app_config.get("api_base_url", DEFAULT_GITHUB_API_BASE_URL)
            ).strip()
            or DEFAULT_GITHUB_API_BASE_URL
        )

        timeout_seconds = github_app_config.get(
            "timeout_seconds", DEFAULT_GITHUB_TIMEOUT_SECONDS
        )
        try:
            timeout_seconds = int(timeout_seconds)
        except (TypeError, ValueError):
            raise UserError("GITHUB_APP.timeout_seconds must be an integer")
        if timeout_seconds <= 0:
            raise UserError("GITHUB_APP.timeout_seconds must be greater than 0")

        install_url = str(github_app_config.get("install_url", "")).strip()

        return cls(
            app_id=app_id,
            private_key=private_key,
            api_base_url=api_base_url.rstrip("/"),
            timeout_seconds=timeout_seconds,
            install_url=install_url,
        )


class GitHubAppService:
    def __init__(self, github_app_config: GitHubAppConfig, session=None):
        self.config = github_app_config
        self.session = session or requests.Session()

    @classmethod
    def from_config(cls, config, session=None):
        return cls(GitHubAppConfig.from_config(config), session=session)

    def build_installation_url(self, target_path: str):
        install_url = self.config.install_url.strip()
        if not install_url:
            raise UnavailableError("GitHub App installation URL is not configured")

        parsed_url = urlparse(install_url)
        query = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
        query["state"] = target_path
        return urlunparse(parsed_url._replace(query=urlencode(query)))

    def get_installation_status(self, owner: str, repo: str):
        try:
            installation = self._get_installation(owner, repo)
        except NotFound:
            return {
                "installed": False,
                "repository": {"owner": owner, "repo": repo},
            }

        return {
            "installed": True,
            "repository": {"owner": owner, "repo": repo},
            "installation_id": installation.get("id"),
            "target": (installation.get("account") or {}).get("login"),
            "target_type": installation.get("target_type"),
            "html_url": installation.get("html_url"),
            "repository_selection": installation.get("repository_selection"),
        }

    def get_organization_installation(self, owner: str):
        try:
            installation = self._get_organization_installation(owner)
        except NotFound:
            return {
                "installed": False,
                "organization": owner,
            }

        return {
            "installed": True,
            "organization": owner,
            "installation_id": installation.get("id"),
            "target": (installation.get("account") or {}).get("login"),
            "target_type": installation.get("target_type"),
            "html_url": installation.get("html_url"),
            "repository_selection": installation.get("repository_selection"),
        }

    def create_installation_token(self, owner: str, repo: str, access: str = "read"):
        installation = self._get_installation(owner, repo)
        token_response = self._create_installation_access_token(
            installation["id"], access=access
        )
        return {
            "token": token_response["token"],
            "expires_at": token_response["expires_at"],
            "repository": {"owner": owner, "repo": repo},
        }

    def list_installation_repositories(self, installation_id):
        token_response = self._create_installation_access_token(
            installation_id, access="read"
        )
        token = token_response["token"]
        repositories = []
        page = 1
        per_page = 100
        while True:
            payload = self._installation_token_request(
                "GET",
                f"/installation/repositories?per_page={per_page}&page={page}",
                token,
            )
            page_repositories = payload.get("repositories") or []
            for repository in page_repositories:
                repositories.append(
                    {
                        "id": repository.get("id"),
                        "name": repository.get("name"),
                        "full_name": repository.get("full_name"),
                        "html_url": repository.get("html_url"),
                        "clone_url": repository.get("clone_url"),
                    }
                )
            if len(page_repositories) < per_page:
                break
            page += 1

        return {
            "installation_id": int(installation_id),
            "repositories": repositories,
        }

    def _app_jwt(self):
        now = datetime.now(UTC)
        payload = {
            "iat": int((now - timedelta(seconds=60)).timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "iss": self.config.app_id,
        }
        return jwt.encode(payload, self.config.private_key, algorithm="RS256")

    def _github_request(self, method: str, path: str, json_body=None):
        url = f"{self.config.api_base_url}{path}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._app_jwt()}",
        }
        try:
            response = self.session.request(
                method,
                url,
                headers=headers,
                json=json_body,
                timeout=self.config.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise BadGatewayError(f"GitHub App request failed: {exc}")

        if response.status_code == 404:
            raise NotFound("GitHub App is not installed on the requested repository")
        if response.status_code >= 400:
            logger.error(
                "GitHub App request failed with status %s for %s %s: %s",
                response.status_code,
                method,
                url,
                response.text,
            )
            raise BadGatewayError(
                f"GitHub App request failed with status {response.status_code}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise BadGatewayError(f"invalid JSON returned from GitHub: {exc}")

    def _installation_token_request(self, method: str, path: str, token: str):
        url = f"{self.config.api_base_url}{path}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
        }
        try:
            response = self.session.request(
                method,
                url,
                headers=headers,
                timeout=self.config.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise BadGatewayError(f"GitHub installation request failed: {exc}")

        if response.status_code >= 400:
            logger.error(
                "GitHub installation request failed with status %s for %s %s: %s",
                response.status_code,
                method,
                url,
                response.text,
            )
            raise BadGatewayError(
                f"GitHub installation request failed with status {response.status_code}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise BadGatewayError(f"invalid JSON returned from GitHub: {exc}")

    def _get_installation(self, owner: str, repo: str):
        return self._github_request("GET", f"/repos/{owner}/{repo}/installation")

    def _get_organization_installation(self, owner: str):
        return self._github_request("GET", f"/orgs/{owner}/installation")

    def _create_installation_access_token(self, installation_id, access: str = "read"):
        if access == "write":
            permissions = DEFAULT_GITHUB_WRITE_PERMISSIONS
        else:
            permissions = DEFAULT_GITHUB_READ_PERMISSIONS
        return self._github_request(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            json_body={"permissions": permissions},
        )
