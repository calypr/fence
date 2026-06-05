import flask
from flask_restful import Resource

from fence.auth import get_jwt, require_auth_header
from fence.config import config
from fence.errors import Forbidden, UserError
from fence.resources.github_app import GitHubAppService


def _authorize_repository(
    owner: str,
    repo: str,
    organization: str = "",
    project: str = "",
    resource_path: str = "",
    access: str = "read",
):
    if not hasattr(flask.current_app, "arborist"):
        raise Forbidden(
            "this fence instance is not configured with arborist; this endpoint is unavailable"
        )

    calypr_org = organization.strip() or owner
    resource = resource_path.strip()
    if not resource:
        calypr_project = project.strip() or repo
        resource = f"/programs/{calypr_org}/projects/{calypr_project}"
    methods = ["read"]
    if access == "write":
        methods = ["create", "write-storage"]
    authorized = flask.current_app.arborist.auth_request(
        jwt=get_jwt(),
        service="fence",
        methods=methods,
        resources=[resource],
    )
    if not authorized:
        if access == "write":
            raise Forbidden(
                "user does not have privileges to mint a write-capable GitHub token for this repository"
            )
        raise Forbidden(
            "user does not have privileges to mint a GitHub token for this repository"
        )


def _authorize_organization(organization: str):
    if not hasattr(flask.current_app, "arborist"):
        raise Forbidden(
            "this fence instance is not configured with arborist; this endpoint is unavailable"
        )

    project_container_resource = f"/programs/{organization}/projects"
    allowed = flask.current_app.arborist.auth_request(
        jwt=get_jwt(),
        service="arborist",
        methods=["create-descendant"],
        resources=[project_container_resource],
    )
    if not allowed:
        raise Forbidden(
            "user does not have privileges to request GitHub App access for this organization"
        )


class GitHubCredentialBroker(Resource):
    @require_auth_header({"github_credentials"})
    def post(self):
        payload = flask.request.get_json(silent=True) or {}
        action = str(payload.get("action", "")).strip()
        service = GitHubAppService.from_config(config)

        if action == "installation_token":
            owner = str(payload.get("owner", "")).strip()
            repo = str(payload.get("repo", "")).strip()
            organization = str(payload.get("organization", "")).strip()
            project = str(payload.get("project", "")).strip()
            resource_path = str(payload.get("resource_path", "")).strip()
            access = str(payload.get("access", "read")).strip().lower() or "read"
            if not owner or not repo:
                raise UserError("request body must include non-empty owner and repo")
            if access not in {"read", "write"}:
                raise UserError("request body access must be one of: read, write")
            _authorize_repository(
                owner,
                repo,
                organization=organization,
                project=project,
                resource_path=resource_path,
                access=access,
            )
            return flask.jsonify(service.create_installation_token(owner, repo, access=access))

        if action == "repository_installation":
            owner = str(payload.get("owner", "")).strip()
            repo = str(payload.get("repo", "")).strip()
            organization = str(payload.get("organization", "")).strip()
            project = str(payload.get("project", "")).strip()
            resource_path = str(payload.get("resource_path", "")).strip()
            if not owner or not repo:
                raise UserError("request body must include non-empty owner and repo")
            _authorize_repository(
                owner,
                repo,
                organization=organization,
                project=project,
                resource_path=resource_path,
            )
            return flask.jsonify(service.get_installation_status(owner, repo))

        if action == "install_url":
            owner = str(payload.get("owner", "")).strip()
            organization = str(payload.get("organization", "")).strip() or owner
            if not owner:
                raise UserError("request body must include non-empty owner")
            redirect_path = str(payload.get("redirect_path", "")).strip() or "/"
            _authorize_organization(organization)
            return flask.jsonify(
                {
                    "install_url": service.build_installation_url(redirect_path),
                    "owner": owner,
                    "organization": organization,
                }
            )

        if action == "organization_installation":
            owner = str(payload.get("owner", "")).strip()
            organization = str(payload.get("organization", "")).strip() or owner
            if not owner:
                raise UserError("request body must include non-empty owner")
            _authorize_organization(organization)
            return flask.jsonify(service.get_organization_installation(owner))

        if action == "installation_repositories":
            installation_id = payload.get("installation_id")
            try:
                installation_id = int(installation_id)
            except (TypeError, ValueError):
                raise UserError("request body must include a positive installation_id")
            if installation_id <= 0:
                raise UserError("request body must include a positive installation_id")
            return flask.jsonify(service.list_installation_repositories(installation_id))

        raise UserError(
            "request body action must be one of: install_url, repository_installation, organization_installation, installation_token, installation_repositories"
        )
