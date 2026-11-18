
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import app.workers.worker as worker

from app.models import (
    Contest,
    JudgingAttempt,
    Organization,
    OrganizationMembership,
    OutboxEvent,
    Participation,
    Problem,
    ProblemVersion,
    Submission,
    TestCase as JudgeTestCase,
    TestSuiteVersion as SuiteVersion,
    User,
)


def create_queued_job(test_engine):
    TestSession = sessionmaker(
        bind=test_engine,
        expire_on_commit=False,
    )

    suffix = uuid4().hex[:12]

    with TestSession() as db:
        organization = Organization(
            name=f"Concurrency Org {suffix}",
            slug=f"concurrency-{suffix}",
        )

        user = User(
            email=f"concurrency-{suffix}@test.dev",
            password_hash="test-hash",
            display_name="Concurrency Participant",
            is_active=True,
        )

        db.add_all([organization, user])
        db.flush()

        db.add(
            OrganizationMembership(
                organization_id=organization.id,
                user_id=user.id,
                role="participant",
            )
        )

        contest = Contest(
            organization_id=organization.id,
            title="Concurrency Test Contest",
            description="Worker concurrency test",
            starts_at=worker.utc_now() - timedelta(hours=1),
            ends_at=worker.utc_now() + timedelta(hours=1),
            duration_minutes=60,
            is_published=True,
        )

        db.add(contest)
        db.flush()

        db.add(
            Participation(
                contest_id=contest.id,
                user_id=user.id,
            )
        )

        problem = Problem(
            contest_id=contest.id,
            slug="concurrency-problem",
            title="Concurrency Problem",
            current_version=1,
        )

        db.add(problem)
        db.flush()

        version = ProblemVersion(
            problem_id=problem.id,
            version=1,
            statement="Print the input",
            input_description="One input",
            output_description="One output",
            points=100,
            time_limit_ms=2000,
            memory_limit_mb=256,
        )

        db.add(version)
        db.flush()

        suite = SuiteVersion(
            problem_version_id=version.id,
            version=1,
        )

        db.add(suite)
        db.flush()

        db.add(
            JudgeTestCase(
                test_suite_version_id=suite.id,
                position=1,
                input_data="hello",
                expected_output="hello",
                is_hidden=True,
            )
        )

        submission = Submission(
            contest_id=contest.id,
            problem_id=problem.id,
            problem_version_id=version.id,
            test_suite_version_id=suite.id,
            user_id=user.id,
            idempotency_key=f"concurrency-{suffix}",
            request_hash="test-hash",
            source_code="print(input())",
            language="python",
            runtime_config={},
            status="queued",
        )

        db.add(submission)
        db.flush()

        attempt = JudgingAttempt(
            submission_id=submission.id,
            attempt_number=1,
            problem_version_id=version.id,
            test_suite_version_id=suite.id,
            status="queued",
            is_authoritative=True,
            retry_count=0,
        )

        db.add(attempt)
        db.flush()

        event = OutboxEvent(
            event_key=worker.event_key_for(attempt),
            event_type="submission.queued",
            payload={
                "submission_id": str(submission.id),
                "attempt_id": str(attempt.id),
                "attempt_number": 1,
            },
        )

        db.add(event)

        job_ids = {
            "attempt_id": attempt.id,
            "submission_id": submission.id,
        }

        db.commit()

        return job_ids


def test_two_workers_cannot_claim_same_event(
    test_engine,
    monkeypatch,
):
    TestSession = sessionmaker(
        bind=test_engine,
        expire_on_commit=False,
    )

    monkeypatch.setattr(
        worker,
        "SessionLocal",
        TestSession,
    )

    job_ids = create_queued_job(test_engine)
    barrier = Barrier(2)

    def competing_worker():
        barrier.wait(timeout=10)
        return worker.claim_one()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(competing_worker)
            for _ in range(2)
        ]

        results = [
            future.result(timeout=20)
            for future in futures
        ]

    claimed_jobs = [
        job for job in results
        if job is not None
    ]

    assert len(claimed_jobs) == 1

    claimed_job = claimed_jobs[0]

    assert claimed_job["attempt_id"] == job_ids["attempt_id"]

    with TestSession() as db:
        attempt = db.get(
            JudgingAttempt,
            job_ids["attempt_id"],
        )

        assert attempt.status == "running"
        assert attempt.worker_token == claimed_job["worker_token"]

        assert db.scalar(
            select(JudgingAttempt.id).where(
                JudgingAttempt.id == job_ids["attempt_id"],
                JudgingAttempt.status == "running",
            )
        ) is not None


def test_stale_worker_cannot_save_result(
    test_engine,
    monkeypatch,
):
    TestSession = sessionmaker(
        bind=test_engine,
        expire_on_commit=False,
    )

    monkeypatch.setattr(
        worker,
        "SessionLocal",
        TestSession,
    )

    job_ids = create_queued_job(test_engine)

    job = worker.claim_one()

    assert job is not None

    replacement_token = uuid4().hex

    # Simulate a new worker taking ownership.
    with TestSession() as db:
        attempt = db.get(
            JudgingAttempt,
            job_ids["attempt_id"],
        )

        attempt.worker_token = replacement_token
        db.commit()

    # The old worker must not overwrite the new worker's result.
    worker.save_result(
        job,
        {
            "verdict": "AC",
            "score": 100,
        },
    )

    with TestSession() as db:
        attempt = db.get(
            JudgingAttempt,
            job_ids["attempt_id"],
        )

        assert attempt.status == "running"
        assert attempt.worker_token == replacement_token
        assert attempt.verdict is None
        assert attempt.score == 0


def test_expired_lease_is_recovered(
    test_engine,
    monkeypatch,
):
    TestSession = sessionmaker(
        bind=test_engine,
        expire_on_commit=False,
    )

    monkeypatch.setattr(
        worker,
        "SessionLocal",
        TestSession,
    )

    job_ids = create_queued_job(test_engine)

    job = worker.claim_one()
    assert job is not None

    with TestSession() as db:
        attempt = db.get(
            JudgingAttempt,
            job_ids["attempt_id"],
        )

        attempt.lease_expires_at = (
            worker.utc_now() - timedelta(minutes=2)
        )

        db.commit()

    recovered = worker.recover_expired_attempts()

    assert recovered == 1

    with TestSession() as db:
        attempt = db.get(
            JudgingAttempt,
            job_ids["attempt_id"],
        )

        event = db.execute(
            select(OutboxEvent).where(
                OutboxEvent.event_key
                == worker.event_key_for(attempt)
            )
        ).scalar_one()

        submission = db.get(
            Submission,
            job_ids["submission_id"],
        )

        assert attempt.status == "queued"
        assert attempt.retry_count == 1
        assert attempt.worker_token is None
        assert attempt.lease_expires_at is None

        assert submission.status == "queued"
        assert event.published_at is None


def test_expired_lease_fails_after_max_retries(
    test_engine,
    monkeypatch,
):
    TestSession = sessionmaker(
        bind=test_engine,
        expire_on_commit=False,
    )

    monkeypatch.setattr(
        worker,
        "SessionLocal",
        TestSession,
    )

    job_ids = create_queued_job(test_engine)

    job = worker.claim_one()
    assert job is not None

    with TestSession() as db:
        attempt = db.get(
            JudgingAttempt,
            job_ids["attempt_id"],
        )

        attempt.retry_count = worker.MAX_RETRIES

        attempt.lease_expires_at = (
            worker.utc_now() - timedelta(minutes=2)
        )

        db.commit()

    recovered = worker.recover_expired_attempts()

    assert recovered == 0

    with TestSession() as db:
        attempt = db.get(
            JudgingAttempt,
            job_ids["attempt_id"],
        )

        submission = db.get(
            Submission,
            job_ids["submission_id"],
        )

        assert attempt.status == "failed"
        assert attempt.verdict == "JUDGE_ERROR"
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import app.workers.worker as worker

from app.models import (
    Contest,
    JudgingAttempt,
    Organization,
    OrganizationMembership,
    OutboxEvent,
    Participation,
    Problem,
    ProblemVersion,
    Submission,
    TestCase as JudgeTestCase,
    TestSuiteVersion as SuiteVersion,
    User,
)


def create_queued_job(test_engine):
    TestSession = sessionmaker(
        bind=test_engine,
        expire_on_commit=False,
    )

    suffix = uuid4().hex[:12]

    with TestSession() as db:
        organization = Organization(
            name=f"Concurrency Org {suffix}",
            slug=f"concurrency-{suffix}",
        )

        user = User(
            email=f"concurrency-{suffix}@test.dev",
            password_hash="test-hash",
            display_name="Concurrency Participant",
            is_active=True,
        )

        db.add_all([organization, user])
        db.flush()

        db.add(
            OrganizationMembership(
                organization_id=organization.id,
                user_id=user.id,
                role="participant",
            )
        )

        contest = Contest(
            organization_id=organization.id,
            title="Concurrency Test Contest",
            description="Worker concurrency test",
            starts_at=worker.utc_now() - timedelta(hours=1),
            ends_at=worker.utc_now() + timedelta(hours=1),
            duration_minutes=60,
            is_published=True,
        )

        db.add(contest)
        db.flush()

        db.add(
            Participation(
                contest_id=contest.id,
                user_id=user.id,
            )
        )

        problem = Problem(
            contest_id=contest.id,
            slug="concurrency-problem",
            title="Concurrency Problem",
            current_version=1,
        )

        db.add(problem)
        db.flush()

        version = ProblemVersion(
            problem_id=problem.id,
            version=1,
            statement="Print the input",
            input_description="One input",
            output_description="One output",
            points=100,
            time_limit_ms=2000,
            memory_limit_mb=256,
        )

        db.add(version)
        db.flush()

        suite = SuiteVersion(
            problem_version_id=version.id,
            version=1,
        )

        db.add(suite)
        db.flush()

        db.add(
            JudgeTestCase(
                test_suite_version_id=suite.id,
                position=1,
                input_data="hello",
                expected_output="hello",
                is_hidden=True,
            )
        )

        submission = Submission(
            contest_id=contest.id,
            problem_id=problem.id,
            problem_version_id=version.id,
            test_suite_version_id=suite.id,
            user_id=user.id,
            idempotency_key=f"concurrency-{suffix}",
            request_hash="test-hash",
            source_code="print(input())",
            language="python",
            runtime_config={},
            status="queued",
        )

        db.add(submission)
        db.flush()

        attempt = JudgingAttempt(
            submission_id=submission.id,
            attempt_number=1,
            problem_version_id=version.id,
            test_suite_version_id=suite.id,
            status="queued",
            is_authoritative=True,
            retry_count=0,
        )

        db.add(attempt)
        db.flush()

        event = OutboxEvent(
            event_key=worker.event_key_for(attempt),
            event_type="submission.queued",
            payload={
                "submission_id": str(submission.id),
                "attempt_id": str(attempt.id),
                "attempt_number": 1,
            },
        )

        db.add(event)

        job_ids = {
            "attempt_id": attempt.id,
            "submission_id": submission.id,
        }

        db.commit()

        return job_ids


def test_two_workers_cannot_claim_same_event(
    test_engine,
    monkeypatch,
):
    TestSession = sessionmaker(
        bind=test_engine,
        expire_on_commit=False,
    )

    monkeypatch.setattr(
        worker,
        "SessionLocal",
        TestSession,
    )

    job_ids = create_queued_job(test_engine)
    barrier = Barrier(2)

    def competing_worker():
        barrier.wait(timeout=10)
        return worker.claim_one()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(competing_worker)
            for _ in range(2)
        ]

        results = [
            future.result(timeout=20)
            for future in futures
        ]

    claimed_jobs = [
        job for job in results
        if job is not None
    ]

    assert len(claimed_jobs) == 1

    claimed_job = claimed_jobs[0]

    assert claimed_job["attempt_id"] == job_ids["attempt_id"]

    with TestSession() as db:
        attempt = db.get(
            JudgingAttempt,
            job_ids["attempt_id"],
        )

        assert attempt.status == "running"
        assert attempt.worker_token == claimed_job["worker_token"]

        assert db.scalar(
            select(JudgingAttempt.id).where(
                JudgingAttempt.id == job_ids["attempt_id"],
                JudgingAttempt.status == "running",
            )
        ) is not None


def test_stale_worker_cannot_save_result(
    test_engine,
    monkeypatch,
):
    TestSession = sessionmaker(
        bind=test_engine,
        expire_on_commit=False,
    )

    monkeypatch.setattr(
        worker,
        "SessionLocal",
        TestSession,
    )

    job_ids = create_queued_job(test_engine)

    job = worker.claim_one()

    assert job is not None

    replacement_token = uuid4().hex

    # Simulate a new worker taking ownership.
    with TestSession() as db:
        attempt = db.get(
            JudgingAttempt,
            job_ids["attempt_id"],
        )

        attempt.worker_token = replacement_token
        db.commit()

    # The old worker must not overwrite the new worker's result.
    worker.save_result(
        job,
        {
            "verdict": "AC",
            "score": 100,
        },
    )

    with TestSession() as db:
        attempt = db.get(
            JudgingAttempt,
            job_ids["attempt_id"],
        )

        assert attempt.status == "running"
        assert attempt.worker_token == replacement_token
        assert attempt.verdict is None
        assert attempt.score == 0


def test_expired_lease_is_recovered(
    test_engine,
    monkeypatch,
):
    TestSession = sessionmaker(
        bind=test_engine,
        expire_on_commit=False,
    )

    monkeypatch.setattr(
        worker,
        "SessionLocal",
        TestSession,
    )

    job_ids = create_queued_job(test_engine)

    job = worker.claim_one()
    assert job is not None

    with TestSession() as db:
        attempt = db.get(
            JudgingAttempt,
            job_ids["attempt_id"],
        )

        attempt.lease_expires_at = (
            worker.utc_now() - timedelta(minutes=2)
        )

        db.commit()

    recovered = worker.recover_expired_attempts()

    assert recovered == 1

    with TestSession() as db:
        attempt = db.get(
            JudgingAttempt,
            job_ids["attempt_id"],
        )

        event = db.execute(
            select(OutboxEvent).where(
                OutboxEvent.event_key
                == worker.event_key_for(attempt)
            )
        ).scalar_one()

        submission = db.get(
            Submission,
            job_ids["submission_id"],
        )

        assert attempt.status == "queued"
        assert attempt.retry_count == 1
        assert attempt.worker_token is None
        assert attempt.lease_expires_at is None

        assert submission.status == "queued"
        assert event.published_at is None


def test_expired_lease_fails_after_max_retries(
    test_engine,
    monkeypatch,
):
    TestSession = sessionmaker(
        bind=test_engine,
        expire_on_commit=False,
    )

    monkeypatch.setattr(
        worker,
        "SessionLocal",
        TestSession,
    )

    job_ids = create_queued_job(test_engine)

    # Prepare this specific attempt directly as an expired running job.
    # Do not call claim_one(), because older queued events may exist.
    with TestSession() as db:
        attempt = db.get(
            JudgingAttempt,
            job_ids["attempt_id"],
        )

        submission = db.get(
            Submission,
            job_ids["submission_id"],
        )

        event = db.execute(
            select(OutboxEvent).where(
                OutboxEvent.event_key
                == worker.event_key_for(attempt)
            )
        ).scalar_one()

        attempt.status = "running"
        attempt.retry_count = worker.MAX_RETRIES
        attempt.worker_token = uuid4().hex
        attempt.lease_expires_at = (
            worker.utc_now() - timedelta(minutes=2)
        )

        submission.status = "running"
        event.published_at = worker.utc_now()

        db.commit()

    recovered = worker.recover_expired_attempts()

    # Exhausted jobs are failed, not requeued.
    assert recovered == 0

    with TestSession() as db:
        attempt = db.get(
            JudgingAttempt,
            job_ids["attempt_id"],
        )

        submission = db.get(
            Submission,
            job_ids["submission_id"],
        )

        assert attempt.status == "failed"
        assert attempt.verdict == "JUDGE_ERROR"
        assert attempt.score == 0
        assert attempt.worker_token is None
        assert attempt.lease_expires_at is None

        assert submission.status == "failed"

        assert attempt.score == 0
        assert attempt.worker_token is None
        assert attempt.lease_expires_at is None

        assert submission.status == "failed"
