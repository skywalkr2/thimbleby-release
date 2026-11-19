"""The stand-in's quota mode (tests/fake_services.py): a per-account limit that refuses like a real mail service."""

import pytest
from starlette.testclient import TestClient

from tests.fake_services import SECURE_SERVICES, Quota, State, build_app


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def rig(tmp_path):
    state = State(tmp_path)
    state.accounts = 2
    client = TestClient(build_app(state, 0, {}))  # the plain-HTTP helper routes
    mail = TestClient(build_app(state, 0, SECURE_SERVICES, helpers=False))  # the mail and calendar service
    tokens = {}
    for n in (0, 1):
        tokens[n] = f"tok-{n}"
        state.access.add(tokens[n])
        state.account_of[tokens[n]] = n
    clock = Clock()

    def arm(**setup):
        r = client.post("/__e2e/quota", json={"rate": 2, "penalty": 10, **setup})
        assert r.json() == {"quota": True}
        state.quota.clock = clock

    def get(account, path="/mail/v1/messages"):
        return mail.get(path, headers={"Authorization": f"Bearer {tokens[account]}"})

    return state, client, clock, arm, get


def test_the_quota_is_off_unless_set(rig):
    state, client, _clock, _arm, get = rig
    assert state.quota is None
    assert all(get(0).status_code == 200 for _ in range(20))
    assert client.get("/__e2e/requests").json() == {"requests": []}


def test_a_burst_above_the_rate_is_refused_and_a_second_later_the_penalty_still_holds(rig):
    _state, _client, clock, arm, get = rig
    arm()
    assert [get(0).status_code for _ in range(3)] == [200, 200, 429]
    clock.now += 5  # inside the penalty, though a second has passed
    assert get(0).status_code == 429


def test_a_request_inside_the_penalty_extends_it_and_every_endpoint_is_refused(rig):
    _state, _client, clock, arm, get = rig
    arm()
    for _ in range(3):
        get(0)
    clock.now += 8
    assert get(0, "/calendar/v1/events").status_code == 429  # another endpoint; extends to 18
    clock.now += 8  # 16: the first penalty has ended, the extended one has not
    assert get(0).status_code == 429
    clock.now += 11
    assert get(0).status_code == 200


def test_requests_spread_over_seconds_stay_under_the_rate(rig):
    _state, _client, clock, arm, get = rig
    arm()
    for _ in range(6):
        assert get(0).status_code == 200
        clock.now += 0.6


def test_another_account_is_unaffected(rig):
    _state, _client, _clock, arm, get = rig
    arm()
    for _ in range(3):
        get(0)
    assert get(1).status_code == 200


@pytest.mark.parametrize("form,status", [("429", 429), ("403", 403)])
def test_each_refusal_form(rig, form, status):
    _state, _client, _clock, arm, get = rig
    arm(form=form, rate=1)
    get(0)
    refused = get(0)
    assert refused.status_code == status
    error = refused.json()["error"]
    if form == "403":
        assert error["errors"][0]["reason"] == "rateLimitExceeded"
    else:
        assert "errors" not in error


def test_the_wait_in_a_header(rig):
    _state, _client, _clock, arm, get = rig
    arm(wait="header", rate=1, penalty=7)
    get(0)
    refused = get(0)
    assert refused.headers["Retry-After"] == "7"
    assert "details" not in refused.json()["error"]


def test_the_wait_as_a_delay_in_the_body(rig):
    _state, _client, _clock, arm, get = rig
    arm(wait="body-delay", rate=1, penalty=7)
    get(0)
    refused = get(0)
    assert "Retry-After" not in refused.headers
    assert refused.json()["error"]["details"] == [{"retryDelay": "7s"}]


def test_the_wait_only_as_a_time_in_the_message(rig):
    _state, _client, clock, arm, get = rig
    arm(wait="message", rate=1, penalty=7)
    get(0)
    refused = get(0)
    error = refused.json()["error"]
    assert "Retry-After" not in refused.headers and "details" not in error
    assert "2027-01-15T08:00:07.000Z" in error["message"]  # the clock's moment plus the penalty


def test_the_log_records_every_request_with_its_answer(rig):
    _state, client, clock, arm, get = rig
    arm(rate=1)
    get(0)
    clock.now += 0.1
    get(0, "/calendar/v1/events")
    get(1)
    one = client.get("/__e2e/requests", params={"account": 1}).json()["requests"]
    assert [(r["endpoint"], r["answer"]) for r in one] == [
        ("/mail/v1/messages", "ok"),
        ("/calendar/v1/events", "refused"),
    ]
    assert one[1]["time"] - one[0]["time"] == pytest.approx(0.1)
    assert len(client.get("/__e2e/requests", params={"account": 2}).json()["requests"]) == 1
    assert len(client.get("/__e2e/requests").json()["requests"]) == 3


def test_a_rate_of_zero_turns_it_off(rig):
    state, client, _clock, arm, get = rig
    arm(rate=1)
    assert client.post("/__e2e/quota", json={"rate": 0}).json() == {"quota": False}
    assert state.quota is None and get(0).status_code == 200 and get(0).status_code == 200


def test_the_flags_set_it_up_and_a_wrong_form_is_refused():
    from tests.fake_services import configure

    state = configure(["--port", "1", "--state", "/nonexistent", "--quota-rate", "3", "--quota-form", "403"])
    assert isinstance(state.quota, Quota) and (state.quota.rate, state.quota.form) == (3, "403")
    with pytest.raises(ValueError):
        Quota(1, 1, form="500")
