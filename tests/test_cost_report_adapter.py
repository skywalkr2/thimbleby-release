"""The native adapter's cost report (design 6.16, "What a provider actually charged"; S-0654): a recorded fictional
report fills each UTC day's real cost, narrowed to a picked key, converted from cents inside the adapter, paged within a
bound, a throttle's wait honored, an expired cursor restarted, a partial read marked, no key means no read, and an
address that is not the report's own host is refused. Everything runs against a stubbed transport."""

from __future__ import annotations

import importlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import yaml

from engine.ai.adapters import ADAPTERS, GENERIC_ADAPTER, make_adapter
from engine.ai.task import AiError
from engine.config.schema import ProviderSettings

FIXTURES = Path(__file__).parent / "fixtures" / "ai"
CLAIMS = yaml.safe_load((FIXTURES / "catalog-claims.yaml").read_text("utf-8"))
NATIVE = CLAIMS["native_adapter"]
REPORT = json.loads((FIXTURES / "cost-report.json").read_text("utf-8"))
MODULE = importlib.import_module(ADAPTERS[NATIVE["adapter"]].__module__)
NOW = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)


def settings(**extra) -> ProviderSettings:
    return ProviderSettings(**{"adapter": NATIVE["adapter"], "base_url": f"https://{MODULE.REPORT_HOST}", **extra})


def adapter_with(handler, billing="admin", **extra):
    return ADAPTERS[NATIVE["adapter"]](
        settings(**extra), "run-key", billing_secret=billing, transport=httpx.MockTransport(handler)
    )


def serving(*answers):
    """A handler giving each answer in turn (a dict is a 200 body, an int a status) and remembering the requests."""
    seen: list[httpx.Request] = []
    queue = list(answers)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        one = queue.pop(0)
        if isinstance(one, httpx.Response):
            return one
        return httpx.Response(one) if isinstance(one, int) else httpx.Response(200, json=one)

    return handler, seen


def read(adapter, **extra):
    return adapter.cost_report(date(2026, 11, 15), date(2026, 11, 18), now=NOW, **extra)


def test_the_report_fills_each_day_converted_from_cents_across_pages():
    handler, seen = serving(REPORT["page_one"], REPORT["page_two"])
    out = read(adapter_with(handler))
    assert not out.partial
    by_day = {d.day: d for d in out.days}
    assert by_day[date(2026, 11, 15)].amount == Decimal("412.80")  # "41280.000000" cents
    assert by_day[date(2026, 11, 16)].amount == Decimal("2.505")
    assert by_day[date(2026, 11, 17)].amount == Decimal("1.50")  # two rows of one day add up
    assert all(d.currency == "USD" and d.scope == "organization" and d.read_at == NOW for d in out.days)
    assert len(seen) == 2 and seen[1].url.params["page"] == "cursor-two"
    first = seen[0]
    assert first.headers["x-api-key"] == "admin"  # the billing key, never the key that runs models
    assert MODULE.COST_BETA in first.headers.values()
    assert first.url.params["time_bucket_width"] == "1d"
    assert first.url.params["starting_at"] == "2026-11-15T00:00:00Z"
    assert first.url.params["ending_at"] == "2026-11-19T00:00:00Z"  # exclusive end: the last day is included
    assert "api_key_ids[]" not in first.url.query.decode()


def test_a_picked_key_narrows_the_report_and_the_scope_is_key():
    handler, seen = serving(REPORT["page_two"])
    out = read(adapter_with(handler, billing_key_id="apikey_example_one"))
    assert seen[0].url.params["api_key_ids[]"] == "apikey_example_one"
    assert {d.scope for d in out.days} == {"key"}


def test_today_and_a_recently_closed_month_are_open_and_an_old_settled_day_is_not():
    rows = [
        {"starting_at": "2026-11-19T00:00:00Z", "cost": {"amount": "100", "currency": "USD"}},
        {"starting_at": "2026-10-20T00:00:00Z", "cost": {"amount": "100", "currency": "USD"}},
        {"starting_at": "2026-09-20T00:00:00Z", "cost": {"amount": "100", "currency": "USD"}},
    ]
    handler, _ = serving({"data": rows[2:], "has_more": False}, {"data": rows[:2], "has_more": False})
    out = adapter_with(handler).cost_report(date(2026, 9, 20), date(2026, 11, 19), now=NOW)
    # October closed 19 days before the read: settled. Today is open. September is long settled.
    assert {d.day: d.open for d in out.days} == {
        date(2026, 9, 20): False,
        date(2026, 10, 20): False,
        date(2026, 11, 19): True,
    }
    handler, _ = serving(
        {"data": [{"starting_at": "2026-10-30T00:00:00Z", "cost": {"amount": "100"}}], "has_more": False}
    )
    soon = datetime(2026, 11, 3, tzinfo=UTC)
    out = adapter_with(handler).cost_report(date(2026, 10, 30), date(2026, 10, 30), now=soon)
    assert out.days[0].open  # a month that closed three days ago may still be revised


def test_a_long_range_is_read_in_windows_of_at_most_31_days():
    empty = {"data": [], "has_more": False}
    handler, seen = serving(empty, empty)
    adapter_with(handler).cost_report(date(2026, 10, 1), date(2026, 11, 19), now=NOW)  # 50 days
    assert len(seen) == 2
    assert seen[0].url.params["starting_at"] == "2026-10-01T00:00:00Z"
    assert seen[0].url.params["ending_at"] == "2026-11-01T00:00:00Z"
    assert seen[1].url.params["starting_at"] == "2026-11-01T00:00:00Z"


def test_the_page_limit_ends_the_read_partial_never_a_total():
    handler, seen = serving(REPORT["page_one"], REPORT["page_two"])
    out = read(adapter_with(handler), pages=1)
    assert out.partial and len(seen) == 1


def test_an_expired_cursor_restarts_from_the_first_page():
    handler, seen = serving(REPORT["page_one"], 410, REPORT["page_one"], REPORT["page_two"])
    out = read(adapter_with(handler))
    assert not out.partial and len(seen) == 4
    assert "page" not in seen[2].url.params  # restarted at page one
    assert {d.day: d.amount for d in out.days}[date(2026, 11, 15)] == Decimal("412.80")  # nothing counted twice


def test_a_throttle_waits_as_asked_then_tries_again():
    waits: list[float] = []
    handler, seen = serving(httpx.Response(429, headers={"retry-after": "7"}), REPORT["page_two"])
    out = read(adapter_with(handler), sleep=waits.append)
    assert waits == [7.0] and len(seen) == 2 and out.days


def test_a_throttle_asking_for_a_long_wait_is_raised_not_slept():
    waits: list[float] = []
    handler, _ = serving(httpx.Response(429, headers={"retry-after": "3600"}))
    with pytest.raises(AiError) as err:
        read(adapter_with(handler), sleep=waits.append)
    assert err.value.kind == "rate_limited" and err.value.retry_after == 3600 and not waits


def test_a_throttle_that_never_ends_is_bounded_by_the_page_limit():
    handler, seen = serving(*[httpx.Response(429, headers={"retry-after": "1"})] * 5)
    out = read(adapter_with(handler), pages=3, sleep=lambda _: None)
    assert out.partial and not out.days and len(seen) == 3


@pytest.mark.parametrize(
    ("status", "body", "kind"),
    [
        (401, {"error": {"type": "authentication_error"}}, "auth"),
        (403, {"error": {"type": "permission_error"}}, "auth"),
        (529, {"error": {"type": "overloaded_error"}}, "rate_limited"),
        (500, {"error": {"type": "api_error"}}, "provider_down"),
    ],
)
def test_a_failed_read_is_classified_from_the_structured_error(status, body, kind):
    handler, _ = serving(httpx.Response(status, json=body))
    with pytest.raises(AiError) as err:
        read(adapter_with(handler))
    assert err.value.kind == kind


def test_a_report_in_another_shape_is_an_invalid_output_not_zero():
    handler, _ = serving({"unexpected": True})
    with pytest.raises(AiError) as err:
        read(adapter_with(handler))
    assert err.value.kind == "invalid_output"


def test_no_billing_key_means_no_read_and_no_request():
    handler, seen = serving(REPORT["page_one"])
    with pytest.raises(AiError) as err:
        read(adapter_with(handler, billing=None))
    assert err.value.kind == "no_key" and not seen


def test_an_address_that_is_not_the_reports_own_host_is_refused_and_sends_nothing():
    handler, seen = serving(REPORT["page_one"])
    with pytest.raises(AiError) as err:
        read(adapter_with(handler, base_url=REPORT["proxy_base_url"]))
    assert err.value.kind == "other" and "another address" in err.value.detail and not seen
    with pytest.raises(AiError):
        adapter_with(handler, base_url=REPORT["proxy_base_url"]).billing_keys()
    assert not seen


def test_the_keys_are_listed_with_name_and_hint_and_archived_ones_left_out():
    handler, seen = serving(REPORT["keys"])
    keys = adapter_with(handler).billing_keys()
    assert [(k.id, k.name, k.hint) for k in keys] == [
        ("apikey_example_one", "Example runs", "sk-example-...abcd"),
        ("apikey_example_three", "Example tests", "sk-example-...mnop"),
    ]
    assert seen[0].headers["x-api-key"] == "admin"


def test_make_adapter_gives_the_billing_key_only_to_an_adapter_that_offers_a_report():
    given = make_adapter(NATIVE["adapter"], settings(), "k", "admin")
    assert given._billing_secret == "admin"
    other = make_adapter(
        GENERIC_ADAPTER, ProviderSettings(adapter=GENERIC_ADAPTER, base_url=REPORT["proxy_base_url"]), "k", "admin"
    )
    assert not hasattr(other, "cost_report")
