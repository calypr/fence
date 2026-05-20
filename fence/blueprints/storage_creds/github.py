import flask
from flask_restful import Resource

from fence.auth import get_jwt, require_auth_header
from fence.config import config
from fence.errors import Forbidden, UserError
from fence.resources.github_app import GitHubAppService


class GitHubInstallationToken(Resource):
    @require_auth_header({"github_credentials"})
    def post(self):
        payload = flask.request.get_json(silent=True) or {}
        owner = str(payload.get("owner", "")).strip()
        repo = str(payload.get("repo", "")).strip()
        if not owner or not repo:
            raise UserError("request body must include non-empty owner and repo")

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

        service = GitHubAppService.from_config(config)
        return flask.jsonify(service.create_installation_token(owner, repo))
