import flask
from flask_restful import Resource

from fence.auth import get_jwt, require_auth_header
from fence.config import config
from fence.errors import Forbidden, UserError
from fence.resources.github_app import GitHubAppService


def _authorize_repository(owner: str, repo: str):
    if not hasattr(flask.current_app, "arborist"):
        raise Forbidden(
            "this fence instance is not configured with arborist; this endpoint is unavailable"
        )

    resource = f"/programs/{owner}/projects/{repo}"
    authorized = flask.current_app.arborist.auth_request(
        jwt=get_jwt(),
        service="fence",
        methods=["read"],
        resources=[resource],
    )
    if not authorized:
        raise Forbidden(
            "user does not have privileges to mint a GitHub token for this repository"
        )


def _authorize_organization(owner: str):
    if not hasattr(flask.current_app, "arborist"):
        raise Forbidden(
            "this fence instance is not configured with arborist; this endpoint is unavailable"
        )

    resource = f"/programs/{owner}"
    authorized = flask.current_app.arborist.auth_request(
        jwt=get_jwt(),
        service="fence",
        methods=["read"],
        resources=[resource],
    )
    if not authorized:
        raise Forbidden(
            "user does not have privileges to request a GitHub App installation URL for this organization"
        )


class GitHubInstallationToken(Resource):
    @require_auth_header({"github_credentials"})
    def post(self):
        payload = flask.request.get_json(silent=True) or {}
        owner = str(payload.get("owner", "")).strip()
        repo = str(payload.get("repo", "")).strip()
        if not owner or not repo:
            raise UserError("request body must include non-empty owner and repo")

        _authorize_repository(owner, repo)

        service = GitHubAppService.from_config(config)
        return flask.jsonify(service.create_installation_token(owner, repo))


class GitHubInstallationURL(Resource):
    @require_auth_header({"github_credentials"})
    def post(self):
        payload = flask.request.get_json(silent=True) or {}
        owner = str(payload.get("owner", "")).strip()
        if not owner:
            raise UserError("request body must include non-empty owner")
        redirect_path = str(payload.get("redirect_path", "")).strip() or "/"

        _authorize_organization(owner)

        service = GitHubAppService.from_config(config)
        return flask.jsonify(
            {
                "install_url": service.build_installation_url(redirect_path),
                "owner": owner,
            }
        )
