"""A failed read of older mail tells the person in plain words, never the service's own text, and a service's answer
over the client's limit is its own kind of failure a connector can skip (a full-read choice once showed "the answer is
larger than 5120 KB" and read nothing)."""

import httpx
import pytest

from engine.connectors import ConnectorError
from engine.net import MAX_BYTES, AnswerTooLarge, WebClient
from engine.sides import words_sheet
from engine.source_intake import older_failure


def test_an_answer_over_the_limit_is_refused_as_too_large_and_is_still_a_connector_error():
    big = httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 2048))
    client = WebClient(["example.com"], max_bytes=1024, transport=big)
    with pytest.raises(AnswerTooLarge) as raised:
        client.get("https" + "://example.com/older")
    assert isinstance(raised.value, ConnectorError) and raised.value.kind == "outage"


def test_the_limit_takes_a_mail_services_largest_message():
    assert MAX_BYTES >= 34 * 1024 * 1024  # a 25 MB attachment, grown by about a third in transit


@pytest.mark.parametrize("kind", ["auth", "no_access", "not_found", "outage", "offline", "throttled"])
def test_every_kind_of_failure_reads_in_plain_words_and_never_quotes_the_service(kind):
    said = older_failure(ConnectorError(kind, "HTTP 503 upstream connect error or disconnect/reset before headers"))
    assert said == words_sheet()[f"full_read.failed.{kind}"]
    assert "HTTP" not in said and "upstream" not in said


def test_a_message_too_large_says_so_in_plain_words():
    said = older_failure(AnswerTooLarge("outage", "the answer is larger than 5120 KB"))
    assert said == words_sheet()["full_read.failed.too_large"] and "KB" not in said
