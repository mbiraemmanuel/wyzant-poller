import pytest
import responses

from wyzant_poller.models import Job
from wyzant_poller.notify import NtfyNotifier

JOB = Job(id="123", title="SAT Math", url="https://www.wyzant.com/tutor/jobs/123", subject="Mathematics")
JOB_NO_SUBJECT = Job(id="124", title="Writing Help", url="https://www.wyzant.com/tutor/jobs/124")


@responses.activate
def test_ntfy_sends_correct_headers():
    responses.add(responses.POST, "https://ntfy.sh/test-topic", status=200)
    NtfyNotifier("https://ntfy.sh", "test-topic").send(JOB)
    req = responses.calls[0].request
    assert req.headers["Click"] == JOB.url
    assert req.headers["Priority"] == "high"
    assert req.headers["Title"] == "New Wyzant Job"
    assert "mathematics" in req.headers["Tags"]


@responses.activate
def test_ntfy_handles_missing_subject():
    responses.add(responses.POST, "https://ntfy.sh/test-topic", status=200)
    NtfyNotifier("https://ntfy.sh", "test-topic").send(JOB_NO_SUBJECT)
    req = responses.calls[0].request
    assert "tutoring" in req.headers["Tags"]


@responses.activate
def test_ntfy_raises_on_server_error():
    responses.add(responses.POST, "https://ntfy.sh/test-topic", status=500)
    with pytest.raises(Exception):
        NtfyNotifier("https://ntfy.sh", "test-topic").send(JOB)


@responses.activate
def test_ntfy_trailing_slash_in_server():
    responses.add(responses.POST, "https://ntfy.sh/my-topic", status=200)
    NtfyNotifier("https://ntfy.sh/", "my-topic").send(JOB)
    assert len(responses.calls) == 1
