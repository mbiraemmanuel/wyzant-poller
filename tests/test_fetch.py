"""
Tests use synthetic HTML matching the selectors confirmed from highered.wyzant.com/tutor/jobs.
"""

import pytest
import responses
import requests

from wyzant_poller.config import Config
from wyzant_poller.fetch import AuthExpiredError, _fetch_html, _fetch_json


SAMPLE_HTML = """
<html><body>
  <div class="academy-card">
    <p class="text-semibold">Alice</p>
    <h3><span>Algebra 2</span></h3>
    <p class="job-description">Need help with quadratics.</p>
    <a href="/tutor/jobapplication?id=ABC123">Apply</a>
  </div>
  <div class="academy-card">
    <p class="text-semibold">Bob</p>
    <h3><span>SAT Math</span></h3>
    <p class="job-description">Preparing for college admission.</p>
    <a href="/tutor/jobapplication?id=DEF456">Apply</a>
  </div>
</body></html>
"""

# Unqualified card: no apply link, should still get a hash-based ID
UNQUALIFIED_HTML = """
<html><body>
  <div class="academy-card">
    <p class="text-semibold">Carol</p>
    <h3><span>USMLE</span></h3>
    <p class="job-description">Preparing for Step 1.</p>
    <a href="/tutor/subjects">View subject qualifications</a>
  </div>
</body></html>
"""

LOGIN_WALL_HTML = """
<html><body>
  <h1>Sign in to continue</h1>
  <form action="/login"><input type="submit" value="Sign In"></form>
</body></html>
"""

SAMPLE_JSON = {
    "jobs": [
        {"id": "201", "title": "Calculus Help", "subject": "Calculus", "path": "/tutor/jobs/201"},
        {"id": "202", "title": "Writing Coach", "subject": "English", "path": "/tutor/jobs/202"},
    ]
}


@pytest.fixture
def config(tmp_path):
    return Config(
        wyzant_cookie=None,
        wyzant_email=None,
        wyzant_password=None,
        jobs_url="https://www.wyzant.com/tutor/jobs",
        jobs_json_endpoint=None,
        ntfy_server="https://ntfy.sh",
        ntfy_topic="test",
        twilio_account_sid=None,
        twilio_auth_token=None,
        twilio_from=None,
        sms_to=[],
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_username=None,
        smtp_password=None,
        email_from=None,
        email_to=[],
        alert_email=None,
        poll_min=150,
        poll_max=210,
        log_level="DEBUG",
        state_dir=tmp_path,
        tz="America/New_York",
    )


@responses.activate
def test_html_parses_job_list(config):
    responses.add(responses.GET, "https://www.wyzant.com/tutor/jobs", body=SAMPLE_HTML)
    jobs = _fetch_html(config, requests.Session())
    assert len(jobs) == 2
    assert jobs[0].id == "ABC123"
    assert "Algebra 2" in jobs[0].title
    assert jobs[0].subject == "Algebra 2"
    assert "jobapplication?id=ABC123" in jobs[0].url


@responses.activate
def test_html_unqualified_card_gets_hash_id(config):
    responses.add(responses.GET, "https://www.wyzant.com/tutor/jobs", body=UNQUALIFIED_HTML)
    jobs = _fetch_html(config, requests.Session())
    assert len(jobs) == 1
    assert jobs[0].id.startswith("h:")  # hash-based ID


@responses.activate
def test_html_raises_on_403(config):
    responses.add(responses.GET, "https://www.wyzant.com/tutor/jobs", status=403)
    with pytest.raises(AuthExpiredError):
        _fetch_html(config, requests.Session())


@responses.activate
def test_html_raises_on_login_wall(config):
    responses.add(responses.GET, "https://www.wyzant.com/tutor/jobs", body=LOGIN_WALL_HTML)
    with pytest.raises(AuthExpiredError):
        _fetch_html(config, requests.Session())


@responses.activate
def test_json_parses_job_list(config):
    json_config = Config(**{**config.__dict__, "jobs_json_endpoint": "https://www.wyzant.com/api/jobs"})
    responses.add(responses.GET, "https://www.wyzant.com/api/jobs", json=SAMPLE_JSON)
    jobs = _fetch_json(json_config, requests.Session())
    assert len(jobs) == 2
    assert jobs[0].id == "201"
    assert jobs[0].subject == "Calculus"
    assert jobs[0].url == "https://www.wyzant.com/tutor/jobs/201"


@responses.activate
def test_json_raises_on_401(config):
    json_config = Config(**{**config.__dict__, "jobs_json_endpoint": "https://www.wyzant.com/api/jobs"})
    responses.add(responses.GET, "https://www.wyzant.com/api/jobs", status=401)
    with pytest.raises(AuthExpiredError):
        _fetch_json(json_config, requests.Session())
