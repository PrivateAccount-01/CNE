"""Versioned, user-scoped external data with enforced expiry."""
from __future__ import annotations
from dataclasses import dataclass, asdict, replace
from enum import Enum
from cne.platform.errors import FreshnessError
import time
import sqlite3
import json


class DataFreshnessStatus(str, Enum):
    NO_DATA = "NO_DATA"
    LOCAL_CACHED = "LOCAL_CACHED"
    STALE = "STALE"
    LIVE_FETCHED = "LIVE_FETCHED"
    LIVE_FETCH_FAILED = "LIVE_FETCH_FAILED"


@dataclass(frozen=True)
class ExternalDataRecord:
    source: str
    key: str
    value: object
    retrieved_at: float
    ttl: float
    version: str | None = None
    freshness_status: DataFreshnessStatus = DataFreshnessStatus.LOCAL_CACHED

    @property
    def expires_at(self):
        return self.retrieved_at + self.ttl

    def is_fresh(self, now=None):
        return (time.time() if now is None else now) < self.expires_at


class ExternalDataCache:
    def __init__(self, database_path=":memory:", codec=None):
        self.db = sqlite3.connect(database_path)
        self.codec = codec
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS external_data (owner TEXT, source TEXT, key TEXT, payload TEXT, PRIMARY KEY(owner,source,key))"
        )
        self.db.commit()

    def put(self, user_id, record):
        if record.ttl < 0:
            raise ValueError("TTL must be nonnegative")
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO external_data VALUES (?,?,?,?)",
                (
                    user_id,
                    record.source,
                    record.key,
                    self.codec.seal(asdict(record), user_id, "external_data")
                    if self.codec
                    else json.dumps(asdict(record), allow_nan=False),
                ),
            )

    def get(self, user_id, source, key, require_fresh=True, now=None):
        row = self.db.execute(
            "SELECT owner,payload FROM external_data WHERE owner=? AND source=? AND key=?",
            (user_id, source, key),
        ).fetchone()
        payload = (
            (
                self.codec.open(row[1], row[0], "external_data")
                if self.codec
                else json.loads(row[1])
            )
            if row
            else None
        )
        record = ExternalDataRecord(**payload) if payload else None
        if record and require_fresh and not record.is_fresh(now):
            raise FreshnessError("STALE")
        return (
            replace(
                record,
                freshness_status=DataFreshnessStatus.LOCAL_CACHED
                if record.is_fresh(now)
                else DataFreshnessStatus.STALE,
            )
            if record
            else None
        )


@dataclass(frozen=True)
class ExternalDataFetchResult:
    status: DataFreshnessStatus
    record: ExternalDataRecord | None = None
    error: str | None = None


class HTTPJSONConnector:
    """Permission-checked, host-allowlisted bounded JSON GET with real cache TTL.

    Redirects are disabled. HTTP is accepted only for explicitly enabled loopback
    integration tests; production requests require HTTPS.
    """

    def __init__(
        self,
        broker,
        cache,
        allowed_hosts,
        timeout_s=10,
        max_bytes=1024 * 1024,
        allow_loopback_http=False,
    ):
        self.broker = broker
        self.cache = cache
        self.allowed_hosts = frozenset(allowed_hosts)
        self.timeout_s = timeout_s
        self.max_bytes = max_bytes
        self.allow_loopback_http = allow_loopback_http

    def fetch(
        self, capability_id, user_id, source, key, url, ttl,
        force_refresh=False, allow_stale_fallback=False,
    ):
        from urllib.parse import urlsplit
        import urllib.request
        import urllib.error

        self.broker.authorize_network(capability_id, user_id)
        parsed = urlsplit(url)
        if (
            parsed.username
            or parsed.password
            or parsed.hostname not in self.allowed_hosts
        ):
            raise PermissionError("ACCESS_DENIED: network host")
        if parsed.scheme != "https" and not (
            self.allow_loopback_http
            and parsed.scheme == "http"
            and parsed.hostname in ("127.0.0.1", "localhost", "::1")
        ):
            raise PermissionError("ACCESS_DENIED: HTTPS required")
        if ttl < 0:
            raise ValueError("Invalid TTL")
        cached = self.cache.get(user_id, source, key, require_fresh=False)
        if cached and cached.is_fresh() and not force_refresh:
            return ExternalDataFetchResult(DataFreshnessStatus.LOCAL_CACHED, cached)

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect()
        )
        try:
            with opener.open(
                urllib.request.Request(url, headers={"Accept": "application/json"}),
                timeout=self.timeout_s,
            ) as response:
                data = response.read(self.max_bytes + 1)
                if len(data) > self.max_bytes:
                    raise ValueError("Response exceeds size limit")
                value = json.loads(data)
                record = ExternalDataRecord(
                    source,
                    key,
                    value,
                    time.time(),
                    ttl,
                    response.headers.get("ETag"),
                    DataFreshnessStatus.LIVE_FETCHED,
                )
            self.cache.put(user_id, record)
            return ExternalDataFetchResult(DataFreshnessStatus.LIVE_FETCHED, record)
        except (OSError, ValueError) as exc:
            fallback = cached if cached and cached.is_fresh() else None
            if fallback is None and cached and allow_stale_fallback:
                fallback = replace(cached, freshness_status=DataFreshnessStatus.STALE)
            return ExternalDataFetchResult(
                DataFreshnessStatus.LIVE_FETCH_FAILED, fallback, type(exc).__name__
            )
