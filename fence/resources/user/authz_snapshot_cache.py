import hashlib
import json
import time
from typing import Any

import flask
from cdislogging import get_logger

from fence.config import config

logger = get_logger(__name__)

_CACHE_EXTENSION_KEY = "authz_snapshot_cache"
_CACHE_DISABLED_UNTIL_KEY = "authz_snapshot_cache_disabled_until"

_REDIS_IMPORT_ERROR = None
try:
    import redis
except Exception as exc:  # pragma: no cover - optional dependency path
    redis = None
    _REDIS_IMPORT_ERROR = exc


def _redis_url() -> str:
    return (
        config.get("AUTHZ_SNAPSHOT_CACHE_REDIS_URL")
        or config.get("REDIS_URL")
        or ""
    ).strip()


def _cache_enabled() -> bool:
    return bool(config.get("AUTHZ_SNAPSHOT_CACHE_ENABLED", True) and _redis_url())


def _cache_ttl_seconds() -> int:
    raw = config.get("AUTHZ_SNAPSHOT_CACHE_TTL_SECONDS", 3600)
    try:
        return max(int(raw), 60)
    except Exception:
        return 3600


def _positive_float_config(name: str, default: float) -> float:
    try:
        return max(float(config.get(name, default)), 0.01)
    except (TypeError, ValueError):
        return default


def _cache_cooldown_seconds() -> float:
    return _positive_float_config(
        "AUTHZ_SNAPSHOT_CACHE_FAILURE_COOLDOWN_SECONDS", 30.0
    )


def _cache_circuit_is_open() -> bool:
    disabled_until = flask.current_app.extensions.get(
        _CACHE_DISABLED_UNTIL_KEY, 0.0
    )
    remaining = float(disabled_until or 0.0) - time.monotonic()
    if remaining <= 0:
        flask.current_app.extensions.pop(_CACHE_DISABLED_UNTIL_KEY, None)
        return False
    logger.info(
        "authz snapshot redis circuit open; bypassing cache for %.0fms",
        remaining * 1000,
    )
    return True


def _mark_cache_unavailable(operation: str, exc: Exception, elapsed_ms: float) -> None:
    cooldown = _cache_cooldown_seconds()
    flask.current_app.extensions[_CACHE_DISABLED_UNTIL_KEY] = (
        time.monotonic() + cooldown
    )
    cache = flask.current_app.extensions.pop(_CACHE_EXTENSION_KEY, None)
    try:
        if cache is not None:
            cache.connection_pool.disconnect()
    except Exception:
        logger.debug("failed to disconnect authz snapshot redis pool", exc_info=True)
    logger.warning(
        "authz snapshot redis operation failed: operation=%s elapsed_ms=%.1f "
        "error_type=%s cooldown_seconds=%.1f error=%s",
        operation,
        elapsed_ms,
        type(exc).__name__,
        cooldown,
        exc,
    )


def _run_cache_operation(cache, operation: str, callback):
    started = time.monotonic()
    logger.info("authz snapshot redis operation started: operation=%s", operation)
    try:
        result = callback()
    except Exception as exc:
        _mark_cache_unavailable(
            operation, exc, (time.monotonic() - started) * 1000
        )
        raise
    logger.info(
        "authz snapshot redis operation completed: operation=%s elapsed_ms=%.1f",
        operation,
        (time.monotonic() - started) * 1000,
    )
    return result


def _cache_client():
    if not _cache_enabled():
        logger.debug("authz snapshot cache disabled or redis url missing")
        return None
    if redis is None:
        logger.warning(
            "authz snapshot cache configured but redis dependency is unavailable: %s",
            _REDIS_IMPORT_ERROR,
        )
        return None
    if _cache_circuit_is_open():
        return None
    cache = flask.current_app.extensions.get(_CACHE_EXTENSION_KEY)
    if cache is not None:
        return cache
    try:
        connect_timeout = _positive_float_config(
            "AUTHZ_SNAPSHOT_CACHE_CONNECT_TIMEOUT_SECONDS", 0.5
        )
        read_timeout = _positive_float_config(
            "AUTHZ_SNAPSHOT_CACHE_READ_TIMEOUT_SECONDS", 1.0
        )
        health_check_interval = _positive_float_config(
            "AUTHZ_SNAPSHOT_CACHE_HEALTH_CHECK_INTERVAL_SECONDS", 30.0
        )
        cache = redis.Redis.from_url(
            _redis_url(),
            decode_responses=True,
            socket_connect_timeout=connect_timeout,
            socket_timeout=read_timeout,
            retry_on_timeout=False,
            health_check_interval=health_check_interval,
            socket_keepalive=True,
        )
        _run_cache_operation(cache, "ping", cache.ping)
        flask.current_app.extensions[_CACHE_EXTENSION_KEY] = cache
        flask.current_app.extensions.pop(_CACHE_DISABLED_UNTIL_KEY, None)
        logger.info(
            "authz snapshot redis cache initialized: connect_timeout_seconds=%.2f "
            "read_timeout_seconds=%.2f health_check_interval_seconds=%.1f",
            connect_timeout,
            read_timeout,
            health_check_interval,
        )
        return cache
    except Exception as exc:
        # _run_cache_operation records operation timing and opens the circuit.
        if _CACHE_DISABLED_UNTIL_KEY not in flask.current_app.extensions:
            _mark_cache_unavailable("initialize", exc, 0.0)
        return None


def _global_epoch_key() -> str:
    return "authz:epoch:global"


def _subject_epoch_key(subject_type: str, subject_name: str) -> str:
    return f"authz:epoch:subject:{subject_type}:{subject_name.strip().lower()}"


def _snapshot_cache_key(username: str) -> str:
    normalized = username.strip().lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"fence:userinfo:authz:{digest}"


def _build_cache_version(username: str, global_version: int, user_version: int) -> str:
    normalized = username.strip().lower()
    body = json.dumps(
        {
            "global_version": global_version,
            "subjects": [
                {
                    "type": "user",
                    "name": normalized,
                    "version": user_version,
                }
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _current_cache_version(cache, username: str) -> str:
    normalized = username.strip().lower()
    values = _run_cache_operation(
        cache,
        "mget_version",
        lambda: cache.mget(
            _global_epoch_key(),
            _subject_epoch_key("user", normalized),
        ),
    )
    raw_global, raw_user = values if isinstance(values, list) and len(values) == 2 else (None, None)
    try:
        global_version = int(raw_global or 0)
    except Exception:
        global_version = 0
    try:
        user_version = int(raw_user or 0)
    except Exception:
        user_version = 0
    return _build_cache_version(normalized, global_version, user_version)


def get_authz_snapshot(username: str) -> tuple[list[str], dict[str, Any]]:
    started = time.monotonic()
    normalized = username.strip().lower()
    if not normalized or not flask.current_app.arborist:
        return [], {}

    logger.info("authz snapshot lookup started for %s", normalized)
    cache = _cache_client()
    cache_key = _snapshot_cache_key(normalized)
    if cache is not None:
        try:
            cached = _run_cache_operation(
                cache, "get_snapshot", lambda: cache.get(cache_key)
            )
            if cached:
                payload = json.loads(cached)
                cache_version = str(payload.get("cache_version") or "").strip()
                current_version = _current_cache_version(cache, normalized)
                resources = payload.get("resources") or []
                authz = payload.get("authz") or {}
                if (
                    cache_version
                    and cache_version == current_version
                    and isinstance(resources, list)
                    and isinstance(authz, dict)
                ):
                    logger.info(
                        "authz snapshot lookup completed for %s: source=redis "
                        "resources=%d elapsed_ms=%.1f",
                        normalized,
                        len(resources),
                        (time.monotonic() - started) * 1000,
                    )
                    return resources, authz
                logger.info(
                    "authz snapshot cache stale for %s: cached_version=%s current_version=%s",
                    normalized,
                    cache_version,
                    current_version,
                )
            else:
                logger.info("authz snapshot cache miss for %s", normalized)
        except Exception as exc:
            logger.warning(
                "authz snapshot cache read failed for %s; falling back to arborist: %s",
                normalized,
                exc,
            )
            cache = None

    arborist_started = time.monotonic()
    auth_mapping = flask.current_app.arborist.auth_mapping(normalized)
    resources = list(auth_mapping.keys())
    logger.info(
        "rebuilt authz snapshot for %s from arborist: resources=%d elapsed_ms=%.1f",
        normalized,
        len(resources),
        (time.monotonic() - arborist_started) * 1000,
    )
    if cache is not None:
        try:
            cache_version = _current_cache_version(cache, normalized)
            payload = json.dumps(
                {
                    "cache_version": cache_version,
                    "resources": resources,
                    "authz": auth_mapping,
                }
            )
            _run_cache_operation(
                cache,
                "set_snapshot",
                lambda: cache.setex(cache_key, _cache_ttl_seconds(), payload),
            )
        except Exception as exc:
            logger.warning("failed to write authz snapshot cache: %s", exc)
    logger.info(
        "authz snapshot lookup completed for %s: source=arborist resources=%d "
        "elapsed_ms=%.1f",
        normalized,
        len(resources),
        (time.monotonic() - started) * 1000,
    )
    return resources, auth_mapping
