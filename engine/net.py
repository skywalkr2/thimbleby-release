"""The core's web client for connectors and plugins: it reaches only the hosts allowed (a plugin's `requires.network`,
or a core source's own address), over HTTPS except on this computer, with a timeout and a size limit, and turns
failures into the connector error kinds. Plugins never open connections themselves.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from engine.connectors import ConnectorError
from engine.gate import reason_code

LOCAL = {"localhost", "127.0.0.1", "::1"}
DEFAULT_TIMEOUT = 20.0
#: The largest answer a service may send: a mail service's largest message, with its attachments, grown by about a
#: third in transit (a 25 MB attachment arrives as about 34 MB).
MAX_BYTES = 40 * 1024 * 1024
#: A transport every client uses when none is given; tests set it to answer without a network.
TRANSPORT: httpx.BaseTransport | None = None


class AnswerTooLarge(ConnectorError):
    """A service's answer bigger than the client takes: a connector may skip the one item it was for."""


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    content: bytes

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        import json

        return json.loads(self.content)


def host_allowed(host: str, allowed: list[str]) -> bool:
    host = host.lower().rstrip(".")
    return any(fnmatch.fnmatch(host, pattern.lower()) for pattern in allowed)


class WebClient:
    """GET, POST, PUT, PATCH and DELETE to allowed hosts only. Raises ConnectorError: offline (no connection could be
    made), outage (timeouts, server errors), auth (401), no_access (403), not_found (404), throttled (429, or 503 with a
    Retry-After; `retry_after` is the wait in seconds). Errors from an answer carry its status, headers and body.
    Every other status comes back as a Response for the caller to read."""

    def __init__(
        self,
        allowed: list[str],
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_bytes: int = MAX_BYTES,
        transport: httpx.BaseTransport | None = None,
        gates: Any = None,
    ):
        self.allowed = list(allowed)
        #: The gates of the account this client reads as (`engine.gate.Gates`), or None for a client with no account.
        self.gates = gates
        self._hosts_used: set[str] = set()
        self.max_bytes = max_bytes
        self._client = httpx.Client(timeout=timeout, follow_redirects=False, transport=transport or TRANSPORT)

    def _check(self, url: str) -> None:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if not host or not host_allowed(host, self.allowed):
            raise ConnectorError("no_access", f"{host or url} isn't a host this may reach")
        if parts.scheme != "https" and not (parts.scheme == "http" and host in LOCAL):
            raise ConnectorError("no_access", "only https addresses are reached, except on this computer")

    def request(self, method: str, url: str, **kwargs: Any) -> Response:
        """One request. A redirect is followed only to an allowed host, at most five times."""
        for _ in range(6):
            self._check(url)
            gate = self._gate(url)
            if gate is not None:
                gate.acquire()
            try:
                with self._client.stream(method, url, **kwargs) as response:
                    if response.is_redirect and response.headers.get("location"):
                        url = str(response.url.join(response.headers["location"]))
                        method, kwargs = ("GET", {}) if response.status_code in (301, 302, 303) else (method, kwargs)
                        continue
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > self.max_bytes:
                            raise AnswerTooLarge("outage", f"the answer is larger than {self.max_bytes // 1024} KB")
                    return _checked(Response(response.status_code, dict(response.headers), bytes(body)))
            except ConnectorError as err:
                if gate is not None and err.kind == "throttled":
                    gate.close(err.retry_after, err.status, reason_code(err))
                raise
            except httpx.ConnectError as err:
                raise ConnectorError("offline", f"couldn't connect: {err}") from None
            except httpx.TimeoutException:
                raise ConnectorError("outage", "it didn't answer in time") from None
            except httpx.HTTPError as err:
                raise ConnectorError("outage", str(err)) from None
        raise ConnectorError("outage", "too many redirects")

    def _gate(self, url: str) -> Any:
        if self.gates is None:
            return None
        host = (urlsplit(url).hostname or "").lower()
        self._hosts_used.add(host)
        return self.gates.for_host(host)

    def note_throttle(self, err: ConnectorError) -> None:
        """A connector raised `throttled` from an answer this client gave it (a refusal with another status, say): the
        gates of the hosts this client reached close for the wait, as for a 429 the client saw itself."""
        if self.gates is not None and err.kind == "throttled" and err.reason != "gate":
            for host in self._hosts_used:
                self.gates.for_host(host).close(err.retry_after, err.status, reason_code(err))

    def get(self, url: str, **kwargs: Any) -> Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> Response:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> Response:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> Response:
        return self.request("DELETE", url, **kwargs)

    def close(self) -> None:
        self._client.close()


#: The longest wait a service's Retry-After is taken at, in seconds.
MAX_RETRY_AFTER = 24 * 3600


def retry_after(headers: dict[str, str], now: float | None = None) -> float | None:
    """A Retry-After header in seconds from now: a number of seconds, or an HTTP date. None when absent or
    unreadable; never more than the host's longest wait. For a connector that raises `ConnectorError("throttled",
    ..., retry_after=retry_after(headers))` itself (a service that says "slow down" with another status, say); the
    web client already does this for 429 and for a 503 with Retry-After."""
    import time
    from email.utils import parsedate_to_datetime

    value = next((v for k, v in headers.items() if k.lower() == "retry-after"), None)
    if not value:
        return None
    value = value.strip()
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = parsedate_to_datetime(value).timestamp() - (time.time() if now is None else now)
        except (TypeError, ValueError):
            return None
    return min(max(seconds, 0.0), MAX_RETRY_AFTER)


def _checked(response: Response) -> Response:
    status = response.status
    answer = {"status": status, "headers": response.headers, "body": response.text}
    if status == 429 or (status == 503 and retry_after(response.headers) is not None):
        wait = retry_after(response.headers)
        raise ConnectorError(
            "throttled", f"the service asked to wait (it answered {status})", retry_after=wait, **answer
        )
    if status == 401:
        raise ConnectorError("auth", "the service asked to sign in again", **answer)
    if status == 403:
        raise ConnectorError("no_access", "the service refused access", **answer)
    if status == 404:
        raise ConnectorError("not_found", "the service says it isn't there", **answer)
    if status >= 500:
        raise ConnectorError("outage", f"the service answered {status}", **answer)
    return response
