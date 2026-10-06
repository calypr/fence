from unittest.mock import Mock

import flask

from fence import error_handler
from fence.errors import Unauthorized


def test_expected_unauthorized_response_has_no_error_traceback(monkeypatch):
    logger = Mock()
    monkeypatch.setattr(error_handler, "logger", logger)
    app = flask.Flask("fence")
    app.register_error_handler(Exception, error_handler.get_error_response)

    @app.get("/private")
    def private():
        raise Unauthorized("Please login")

    response = app.test_client().get("/private")

    assert response.status_code == 401
    assert b"Please login" in response.data
    logger.debug.assert_called_once()
    logger.info.assert_not_called()
    logger.error.assert_not_called()


def test_unexpected_server_error_keeps_a_single_traceback(monkeypatch):
    logger = Mock()
    monkeypatch.setattr(error_handler, "logger", logger)
    app = flask.Flask("fence")

    try:
        raise RuntimeError("unexpected failure")
    except RuntimeError as error:
        with app.test_request_context("/user/user"):
            _, status = error_handler.get_error_response(error)

    assert status == 500
    logger.error.assert_called_once()
    assert "RuntimeError: unexpected failure" in logger.error.call_args.args[0]
    logger.debug.assert_not_called()
    logger.info.assert_not_called()
