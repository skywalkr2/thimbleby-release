"""Adapter for the recommended service's own messages interface, rather than its chat-completions compatibility layer.

The native interface takes the stable part of a packet as a cached prefix, takes a tier's effort in its own setting,
and reports a refusal as its own stop reason, none of which the compatibility layer offers. It needs a base URL, a key
and model ids, all from config.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

import httpx

from engine.ai.adapters.openai_compatible import _int, _retry_after, transport_error
from engine.ai.task import (
    AiError,
    AiResult,
    AiTask,
    BillingKey,
    CostReadout,
    ErrorKind,
    ModelInfo,
    ProviderCostDay,
    says_no_credit,
    says_retired,
)

#: The interface's version header, which every request carries.
API_VERSION = "2023-06-01"
#: What to tell the person when the service stopped the answer under its own safety policy.
REFUSAL_TEXT = "the service declined to answer under its own safety policy"

#: Error types in an error body, by the kind of failure they mean. Only the structured type is read, never the message.
ERROR_TYPES: dict[str, ErrorKind] = {
    "authentication_error": "auth",
    "permission_error": "auth",
    "billing_error": "quota",
    "rate_limit_error": "rate_limited",
    "overloaded_error": "rate_limited",
    "api_error": "provider_down",
}
#: What a status means when the body carries no error type this adapter knows.
STATUS_KINDS: dict[int, ErrorKind] = {401: "auth", 403: "auth", 402: "quota", 429: "rate_limited", 529: "rate_limited"}
#: The host the cost report and the organization's key list are read from, and nowhere else: the billing key is sent
#: only here, so an account whose address is another host (a proxy) never reads a report.
REPORT_HOST = "api.anthropic.com"
COST_PATH = "/v1/organizations/analytics/cost"
KEYS_PATH = "/v1/organizations/api_keys"
#: The report's beta header, as its documentation gives it.
COST_BETA = "analytics-usage-cost-2026-08-24"
#: The most days one request of the report may span.
COST_WINDOW_DAYS = 31
#: The most rows asked for in one page of the report.
COST_PAGE_ROWS = 1000
#: The longest wait a throttled request honors in one go; a longer requested wait is raised to the caller instead.
COST_MAX_WAIT = 60.0
#: How many days after a month closes the provider may still revise that month's figures.
REVISED_DAYS_AFTER_MONTH = 7
#: Stop reasons that mean the answer was cut off before it was complete.
CUT_OFF_STOPS = frozenset({"max_tokens", "model_context_window_exceeded"})


class AnthropicMessagesAdapter:
    name = "anthropic-messages"
    #: This service lists each model's capabilities, so a caller that has the catalog's entry hands it over in
    #: `AiTask.model_info` (the router from its kept catalog, the smoke test from one read of the list).
    reads_capabilities = True

    def __init__(
        self,
        settings: Any,
        secret: str | None = None,
        *,
        billing_secret: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        if not settings.base_url:
            raise AiError("other", "this account has no base_url")
        self.settings = settings
        headers = {"Content-Type": "application/json", "anthropic-version": API_VERSION}
        if secret:
            headers["x-api-key"] = secret
        base = settings.base_url.rstrip("/")
        # The address of the compatibility layer ends in /v1, which this interface's paths already carry.
        base = base.removesuffix("/v1")
        self._client = httpx.Client(
            base_url=base, headers=headers, timeout=settings.timeout_seconds, transport=transport
        )
        self._billing_secret = billing_secret
        self._transport = transport
        self._billing_client: httpx.Client | None = None

    def run(self, task: AiTask, model: str) -> AiResult:
        if task.audio is not None:
            raise AiError("other", "this adapter doesn't turn speech into text")
        body = request_body(
            task,
            model,
            send_temperature=getattr(self.settings, "send_temperature", True),
            thinking_room=getattr(self.settings, "thinking_room", 0),
        )
        started = time.monotonic()
        try:
            response = self._client.post("/v1/messages", json=body)
        except httpx.TimeoutException as err:
            raise AiError("timeout", str(err)) from None
        except httpx.TransportError as err:
            raise transport_error(err, self.settings.base_url) from None
        seconds = time.monotonic() - started
        if response.status_code >= 400:
            raise classify_http_error(response)
        try:
            data = response.json()
            blocks = data["content"]
            if not isinstance(blocks, list):
                raise TypeError("content is not a list")
            text = "".join(b["text"] for b in blocks if isinstance(b, dict) and b.get("type") == "text" and "text" in b)
            stop = data.get("stop_reason")
        except (ValueError, KeyError, TypeError, AttributeError):
            raise AiError("invalid_output", "the response wasn't in the expected format") from None
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        # `input_tokens` is only what wasn't read from or written to the cache; the router counts it as the whole
        # prompt with the cached part inside it, so the three are added up here.
        read = _int(usage.get("cache_read_input_tokens"))
        written = _int(usage.get("cache_creation_input_tokens"))
        fresh = _int(usage.get("input_tokens"))
        total = None if fresh is None else fresh + (read or 0) + (written or 0)
        refused = stop == "refusal"
        return AiResult(
            text=text,
            model_served=str(data.get("model") or model),
            seconds=seconds,
            input_tokens=total,
            output_tokens=_int(usage.get("output_tokens")),
            cached_input_tokens=read,
            truncated=stop in CUT_OFF_STOPS,
            refused=refused,
            refusal=REFUSAL_TEXT if refused else None,
        )

    def capability_notes(self, task: AiTask) -> list[str]:
        """What the task asks for that the model's listed capabilities don't allow, in plain words, one line each:
        what was therefore left out of the request. Empty when everything asked for is sent (or when the list says
        nothing about the model, which is sent as asked)."""
        return capability_notes(task)

    def count_tokens(self, task: AiTask, model: str) -> int:
        """The tokens the service would count for this request, without running it: its count request takes the
        model, the system prompt and the messages of the request the run would send, and answers with the input
        tokens. Nothing but what is counted is sent: no answer limit, temperature, effort or cache marker."""
        body = request_body(task, model, send_temperature=False)
        system = [{"type": "text", "text": block["text"]} for block in body["system"]]
        count = {"model": model, "messages": body["messages"], **({"system": system} if system else {})}
        try:
            response = self._client.post("/v1/messages/count_tokens", json=count)
        except httpx.TimeoutException as err:
            raise AiError("timeout", str(err)) from None
        except httpx.TransportError as err:
            raise transport_error(err, self.settings.base_url) from None
        if response.status_code >= 400:
            raise classify_http_error(response)
        try:
            tokens = _int(response.json().get("input_tokens"))
        except (ValueError, AttributeError):
            tokens = None
        if tokens is None:
            raise AiError("invalid_output", "the count wasn't in the expected format")
        return tokens

    def identity(self) -> None:
        """Not applicable: the account is a key, not a sign-in of a person."""
        return None

    def catalog(self) -> dict[str, ModelInfo]:
        """The account's models with their context and output limits; empty when the list can't be read. The service's
        list carries no prices, so those come from config."""
        try:
            return self.list_models()
        except AiError:
            return {}

    def list_models(self) -> dict[str, ModelInfo]:
        """The model list, raising `AiError` with the kind of failure (a key not accepted, the service down) instead of
        returning nothing, so a setup screen can say what went wrong."""
        out: dict[str, ModelInfo] = {}
        after: str | None = None
        for _ in range(max(1, getattr(self.settings, "model_list_pages", 10))):
            items, more = self._model_page(after)
            before = len(out)
            for item in items:
                if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                    continue
                efforts, adaptive = listed_capabilities(item.get("capabilities"))
                out[item["id"]] = ModelInfo(
                    context_tokens=_int(item.get("max_input_tokens")),
                    max_output_tokens=_int(item.get("max_tokens")),
                    efforts=efforts,
                    adaptive_thinking=adaptive,
                    released=_released(item.get("created_at")),
                    retired=True if item.get("deprecated") is True else None,
                    reads_images=_listed_image_input(item.get("capabilities")),
                )
            if more is None or more == after or len(out) == before:
                break
            after = more
        return out

    def _model_page(self, after: str | None) -> tuple[list[Any], str | None]:
        """One page of the model list and, when the service says more follow, the id to ask for the page after."""
        try:
            response = self._client.get("/v1/models", params={"after_id": after} if after else None)
        except httpx.TimeoutException as err:
            raise AiError("timeout", str(err)) from None
        except httpx.TransportError as err:
            raise transport_error(err, self.settings.base_url) from None
        if response.status_code >= 400:
            raise classify_http_error(response)
        try:
            body = response.json()
            items = body.get("data") or []
            last = body.get("last_id")
            more = last if body.get("has_more") is True and isinstance(last, str) and last else None
        except (ValueError, AttributeError):
            raise AiError("invalid_output", "the model list wasn't in the expected format") from None
        return (items if isinstance(items, list) else []), more

    # ---- what the provider charged ------------------------------------------------------------------------------

    def _billing(self) -> httpx.Client:
        """The client for the report host, made once, with the billing key. Refused (with the reason in plain words)
        when the account has no billing key or its address is not the report's own host."""
        if not self._billing_secret:
            raise AiError("no_key", "this account has no billing key")
        if urlsplit(self.settings.base_url).hostname != REPORT_HOST:
            raise AiError(
                "other",
                "this account reaches its service through another address, and the billing key is sent only to the "
                "service's own address",
            )
        if self._billing_client is None:
            self._billing_client = httpx.Client(
                base_url=f"https://{REPORT_HOST}",
                headers={
                    "x-api-key": self._billing_secret,
                    "anthropic-version": API_VERSION,
                    "anthropic-beta": COST_BETA,
                },
                timeout=self.settings.timeout_seconds,
                transport=self._transport,
            )
        return self._billing_client

    def _billing_get(self, path: str, params: list[tuple[str, str]]) -> httpx.Response:
        try:
            return self._billing().get(path, params=params)
        except httpx.TimeoutException as err:
            raise AiError("timeout", str(err)) from None
        except httpx.TransportError as err:
            raise transport_error(err, f"https://{REPORT_HOST}") from None

    def billing_keys(self) -> list[BillingKey]:
        """The organization's API keys (id, name and the hint the provider shows), read with the billing key, for the
        person to pick the key this account runs with. Archived keys are left out. Reads at most five pages."""
        found: list[BillingKey] = []
        after: str | None = None
        for _ in range(5):
            params = [("limit", "100")] + ([("after_id", after)] if after else [])
            response = self._billing_get(KEYS_PATH, params)
            if response.status_code >= 400:
                raise classify_http_error(response)
            try:
                body = response.json()
                items = body["data"]
                last = body.get("last_id")
                more = body.get("has_more") is True and isinstance(last, str) and bool(last)
            except (ValueError, KeyError, TypeError, AttributeError):
                raise AiError("invalid_output", "the list of keys wasn't in the expected format") from None
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                    continue
                if item.get("status") == "archived":
                    continue
                name = item.get("name") if isinstance(item.get("name"), str) else ""
                hint = item.get("partial_key_hint") if isinstance(item.get("partial_key_hint"), str) else ""
                found.append(BillingKey(id=item["id"], name=name, hint=hint))
            if not more or last == after:
                break
            after = last
        return found

    def cost_report(
        self,
        day_from: date,
        day_to: date,
        *,
        pages: int = 20,
        sleep: Callable[[float], None] = time.sleep,
        now: datetime | None = None,
    ) -> CostReadout:
        """What the provider charged for each UTC day from `day_from` to `day_to` (both included), one
        `ProviderCostDay` per day and currency. Narrowed to the key picked on the account when there is one (scope
        `key`), else the whole organization.

        Reads in windows of at most 31 days. `pages` bounds every request of the read together (a restart after an
        expired cursor and a try after a throttle count too); reaching it ends the read `partial`. A throttle's wait is
        honored with `sleep` when it is short, and raised (`rate_limited`, with the wait) when it is longer; a cursor
        the provider expired (410) restarts that window from its first page."""
        read_at = now or datetime.now(UTC)
        key_id = getattr(self.settings, "billing_key_id", None)
        scope = "key" if key_id else "organization"
        totals: dict[tuple[date, str], Decimal] = {}
        budget = max(1, pages)
        partial = False
        start = day_from
        while start <= day_to and not partial:
            end = min(day_to, start + timedelta(days=COST_WINDOW_DAYS - 1))
            budget, partial = self._read_window(start, end, key_id, budget, sleep, totals)
            start = end + timedelta(days=1)
        days = [
            ProviderCostDay(
                day=day,
                amount=amount,
                currency=currency,
                scope=scope,
                read_at=read_at,
                open=_still_open(day, read_at),
            )
            for (day, currency), amount in sorted(totals.items())
        ]
        return CostReadout(days=days, partial=partial)

    def _read_window(
        self,
        start: date,
        end: date,
        key_id: str | None,
        budget: int,
        sleep: Callable[[float], None],
        totals: dict[tuple[date, str], Decimal],
    ) -> tuple[int, bool]:
        """One window of the report, page after page. Returns the requests left and whether the budget ran out."""
        base = [
            ("starting_at", f"{start.isoformat()}T00:00:00Z"),
            ("ending_at", f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z"),
            ("time_bucket_width", "1d"),
            ("limit", str(COST_PAGE_ROWS)),
        ]
        if key_id:
            base.append(("api_key_ids[]", key_id))
        page: str | None = None
        rows: dict[tuple[date, str], Decimal] = {}
        while True:
            if budget <= 0:
                totals.update(rows)
                return 0, True
            budget -= 1
            response = self._billing_get(COST_PATH, base + ([("page", page)] if page else []))
            if response.status_code == 410:  # the cursor expired: this window starts again from its first page
                page, rows = None, {}
                continue
            if response.status_code == 429:
                err = classify_http_error(response)
                if err.retry_after is None or err.retry_after > COST_MAX_WAIT:
                    raise err
                sleep(err.retry_after)
                continue
            if response.status_code >= 400:
                raise classify_http_error(response)
            try:
                body = response.json()
                data = body["data"]
                more = body.get("has_more") is True
                next_page = body.get("next_page")
                if not isinstance(data, list):
                    raise TypeError("data is not a list")
                for row in data:
                    _add_row(rows, row)
            except (ValueError, KeyError, TypeError, AttributeError, InvalidOperation):
                raise AiError("invalid_output", "the cost report wasn't in the expected format") from None
            if not more or not isinstance(next_page, str) or not next_page or next_page == page:
                totals.update(rows)
                return budget, False
            page = next_page


def _add_row(into: dict[tuple[date, str], Decimal], row: Any) -> None:
    """Add one report row to the day it starts on (UTC). The row's amount is a decimal string in cents."""
    cost = row["cost"]
    day = datetime.fromisoformat(str(row["starting_at"]).replace("Z", "+00:00")).astimezone(UTC).date()
    currency = str(cost.get("currency") or "USD").upper()
    amount = Decimal(str(cost["amount"])) / 100
    into[(day, currency)] = into.get((day, currency), Decimal(0)) + amount


def _still_open(day: date, read_at: datetime) -> bool:
    """Whether the provider may still revise the day: today or later, or a day of a month that closed less than a
    week before the read."""
    read_day = read_at.astimezone(UTC).date()
    if day >= read_day:
        return True
    first_of_next = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
    return read_day < first_of_next + timedelta(days=REVISED_DAYS_AFTER_MONTH)


def _released(value: Any) -> str | None:
    """The date and time the list says a model was made, as ISO text, or None when it gives none or not a date."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC).isoformat()
    except ValueError:
        return None


def _supported(node: Any) -> bool | None:
    """The `supported` flag of one node of a capability tree, or None when the node or the flag isn't there."""
    flag = node.get("supported") if isinstance(node, dict) else None
    return flag if isinstance(flag, bool) else None


def listed_capabilities(tree: Any) -> tuple[list[str] | None, bool | None]:
    """The effort levels a model takes and whether it can think on its own, from the model list's capability tree.

    Each is None when the tree doesn't carry it (unknown). The effort node says `supported` and then one node per
    level it takes; a model whose node says it isn't supported takes none, which is an empty list, not unknown. Whether
    thinking can be turned off, and at which efforts, is not read: the tree has no node for it."""
    if not isinstance(tree, dict):
        return None, None
    node = tree.get("effort")
    levels = [k for k, v in node.items() if k != "supported" and _supported(v)] if isinstance(node, dict) else []
    efforts: list[str] | None = None
    if _supported(node) is False:
        efforts = []
    elif _supported(node) is True and levels:
        efforts = levels
    thinking = tree.get("thinking")
    types = thinking.get("types") if isinstance(thinking, dict) else None
    adaptive = _supported(types.get("adaptive")) if isinstance(types, dict) else None
    return efforts, adaptive


def _listed_image_input(tree: Any) -> bool | None:
    """Whether the model's capability listing explicitly says it takes image input."""
    node = tree.get("image_input") if isinstance(tree, dict) else None
    supported = _supported(node)
    return supported


def _effort_taken(task: AiTask) -> bool:
    """Whether the tier's effort is sent: when the model's listed efforts include it, or when they aren't known."""
    info = task.model_info
    return bool(task.effort) and (info is None or info.efforts is None or task.effort in info.efforts)


def _thinking_off(task: AiTask) -> bool:
    """Whether thinking is turned off: when the tier asks for it and the model's listed capabilities accept it at the
    tier's effort. Never when the list doesn't say."""
    info = task.model_info
    if task.thinking != "off" or info is None or not info.thinking_off_efforts:
        return False
    return bool(task.effort) and _effort_taken(task) and task.effort in info.thinking_off_efforts


def capability_notes(task: AiTask) -> list[str]:
    """Plain-words reasons for each setting of the task that the model's listed capabilities don't allow, so the
    smoke test can say what was left out instead of dropping it silently."""
    info = task.model_info
    notes: list[str] = []
    if task.effort and info is not None and info.efforts is not None and task.effort not in info.efforts:
        notes.append(
            f"this model takes effort {', '.join(info.efforts)}, so {task.effort} was left out and the model uses "
            "its own"
            if info.efforts
            else f"this model takes no effort setting, so {task.effort} was left out"
        )
    if task.thinking == "off" and not _thinking_off(task):
        if info is None or info.thinking_off_efforts is None:
            notes.append("the service doesn't say this model's thinking can be turned off, so thinking was left on")
        elif not info.thinking_off_efforts:
            notes.append("this model's thinking can't be turned off, so it was left on")
        elif not task.effort:
            notes.append("thinking can be turned off only at an effort this tier hasn't set, so it was left on")
        else:
            taken = ", ".join(info.thinking_off_efforts)
            notes.append(
                f"this model's thinking can be turned off only at effort {taken}, not {task.effort}, so it was left on"
            )
    return notes


def request_body(task: AiTask, model: str, *, send_temperature: bool, thinking_room: int = 0) -> dict[str, Any]:
    """The request for one task: the instructions and then the stable part as the system prompt, with the cache marker
    on the last of them so the whole stable prefix is cached, and the request as the one user turn.

    The answer limit leaves `thinking_room` tokens beyond the task's own for a model whose listed capabilities say it
    thinks on its own (and whose thinking isn't turned off), within the model's own output limit, so thinking never
    uses up the room the answer needs. The effort goes only where the model's listed efforts include it."""
    system = [{"type": "text", "text": text} for text in (task.instructions, task.stable) if text]
    if system:
        system[-1]["cache_control"] = {"type": "ephemeral"}
    off = _thinking_off(task)
    info = task.model_info
    limit = task.max_output
    if info is not None and info.adaptive_thinking and not off and thinking_room > 0:
        limit = task.max_output + thinking_room
        if info.max_output_tokens is not None:
            limit = max(task.max_output, min(limit, info.max_output_tokens))
    user_content: str | list[dict[str, Any]] = task.request
    if task.image is not None:
        user_content = [
            {"type": "text", "text": task.request},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": task.image.media_type,
                    "data": base64.b64encode(task.image.data).decode("ascii"),
                },
            },
        ]
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": limit,
        "system": system,
        "messages": [{"role": "user", "content": user_content}],
    }
    if send_temperature:
        body["temperature"] = task.temperature
    if _effort_taken(task):
        body["output_config"] = {"effort": task.effort}
    if off:
        body["thinking"] = {"type": "disabled"}
    return body


def _error_type(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    error = body.get("error") if isinstance(body, dict) else None
    kind = error.get("type") if isinstance(error, dict) else None
    return kind if isinstance(kind, str) else ""


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    return message if isinstance(message, str) else ""


def classify_http_error(response: httpx.Response) -> AiError:
    """Turn an HTTP error into an error kind from the error body's own type, or from the status when the body gives
    none this adapter knows, never from its wording."""
    status = response.status_code
    detail = f"HTTP {status}: {response.text[:500]}"
    kind: ErrorKind | None = ERROR_TYPES.get(_error_type(response)) or STATUS_KINDS.get(status)
    if kind is None and status in (400, 403) and says_no_credit(_error_message(response)):
        kind = "quota"  # the service answers an empty balance as a bad request; it is no credit, never retried
    if kind is None and status in (400, 404, 410) and says_retired(_error_message(response)):
        kind = "model_retired"
    if kind is None:
        kind = "provider_down" if status >= 500 else "other"
    if kind in ("quota", "rate_limited", "provider_down"):
        return AiError(kind, detail, retry_after=_retry_after(response))
    return AiError(kind, detail)
