import hashlib
import json
from typing import Any

import flask
from cdislogging import get_logger

from fence.config import config

logger = get_logger(__name__)

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
    cache = flask.current_app.extensions.get("authz_snapshot_cache")
    if cache is not None:
        return cache
    try:
        cache = redis.Redis.from_url(_redis_url(), decode_responses=True)
        cache.ping()
        flask.current_app.extensions["authz_snapshot_cache"] = cache
        logger.info("authz snapshot redis cache initialized")
        return cache
    except Exception as exc:
        logger.warning("failed to initialize authz snapshot redis cache: %s", exc)
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
    values = cache.mget(
        _global_epoch_key(),
        _subject_epoch_key("user", normalized),
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
    normalized = username.strip().lower()
    if not normalized or not flask.current_app.arborist:
        return [], {}

    cache = _cache_client()
    cache_key = _snapshot_cache_key(normalized)
    if cache is not None:
        try:
            cached = cache.get(cache_key)
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
                    logger.debug(
                        "authz snapshot cache hit for %s: resources=%d",
                        normalized,
                        len(resources),
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
            logger.warning("failed to read authz snapshot cache: %s", exc)

    auth_mapping = flask.current_app.arborist.auth_mapping(normalized)
    resources = list(auth_mapping.keys())
    logger.info(
        "rebuilt authz snapshot for %s from arborist: resources=%d",
        normalized,
        len(resources),
    )
    if cache is not None:
        try:
            cache_version = _current_cache_version(cache, normalized)
            cache.setex(
                cache_key,
                _cache_ttl_seconds(),
                json.dumps(
                    {
                        "cache_version": cache_version,
                        "resources": resources,
                        "authz": auth_mapping,
                    }
                ),
            )
        except Exception as exc:
            logger.warning("failed to write authz snapshot cache: %s", exc)
    return resources, auth_mapping
