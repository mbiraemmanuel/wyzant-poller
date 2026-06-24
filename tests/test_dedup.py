import pytest

from wyzant_poller.models import Job
from wyzant_poller.store import Store

JOBS = [
    Job(id="1", title="Algebra Tutor", url="https://www.wyzant.com/tutor/jobs/1", subject="Algebra"),
    Job(id="2", title="SAT Prep", url="https://www.wyzant.com/tutor/jobs/2", subject="SAT"),
    Job(id="3", title="GED Help", url="https://www.wyzant.com/tutor/jobs/3", subject="GED"),
]


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.db")
    yield s
    s.close()


def test_first_run_establishes_baseline_silently(store):
    assert not store.is_baseline_established()
    store.establish_baseline(JOBS)
    assert store.is_baseline_established()
    assert store.new_jobs(JOBS) == []


def test_new_job_detected_after_baseline(store):
    store.establish_baseline(JOBS[:2])
    new = store.new_jobs(JOBS)
    assert len(new) == 1
    assert new[0].id == "3"


def test_empty_baseline_then_all_jobs_are_new(store):
    store.establish_baseline([])
    new = store.new_jobs(JOBS)
    assert len(new) == 3


def test_mark_seen_prevents_re_alert(store):
    store.establish_baseline([])
    store.mark_seen(JOBS[:1])
    assert store.new_jobs(JOBS[:1]) == []
    assert len(store.new_jobs(JOBS)) == 2


def test_survives_restart(tmp_path):
    db = tmp_path / "test.db"
    s1 = Store(db)
    s1.establish_baseline(JOBS)
    s1.close()

    s2 = Store(db)
    assert s2.is_baseline_established()
    assert s2.new_jobs(JOBS) == []
    s2.close()


def test_new_jobs_empty_input(store):
    store.establish_baseline(JOBS)
    assert store.new_jobs([]) == []
