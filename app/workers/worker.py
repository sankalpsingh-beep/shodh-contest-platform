import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, update

from app.database import SessionLocal
from app.judge.docker_runner import DockerPythonRunner
from app.models import (
    JudgingAttempt,
    OutboxEvent,
    ProblemVersion,
    Submission,
    TestCase,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("shodh.worker")

LEASE_SECONDS = 60
HEARTBEAT_SECONDS = 15
MAX_RETRIES = 3
POLL_INTERVAL = float(os.getenv("WORKER_POLL_INTERVAL", "2"))


def utc_now():
    return datetime.now(timezone.utc)


def event_key_for(attempt):
    return f"judge:{attempt.submission_id}:attempt:{attempt.attempt_number}"


def recover_expired_attempts():
    """Requeue work whose worker lease expired."""
    with SessionLocal() as db:
        now = utc_now()

        attempts = db.execute(
            select(JudgingAttempt)
            .where(
                JudgingAttempt.status == "running",
                JudgingAttempt.lease_expires_at <= now,
            )
            .order_by(JudgingAttempt.created_at)
            .limit(20)
            .with_for_update(skip_locked=True)
        ).scalars().all()

        recovered = 0

        for attempt in attempts:
            submission = db.get(Submission, attempt.submission_id)
            event = db.execute(
                select(OutboxEvent)
                .where(OutboxEvent.event_key == event_key_for(attempt))
                .with_for_update()
            ).scalar_one_or_none()

            if attempt.retry_count >= MAX_RETRIES:
                attempt.status = "failed"
                attempt.verdict = "JUDGE_ERROR"
                attempt.score = 0
                attempt.completed_at = now
                attempt.worker_token = None
                attempt.lease_expires_at = None

                if submission:
                    submission.status = "failed"

                logger.error("Expired attempt exhausted retries: %s", attempt.id)
            else:
                attempt.retry_count += 1
                attempt.status = "queued"
                attempt.worker_token = None
                attempt.lease_expires_at = None

                if submission:
                    submission.status = "queued"

                if event:
                    event.published_at = None

                recovered += 1
                logger.warning("Recovered expired attempt: %s", attempt.id)

        db.commit()
        return recovered


def claim_one():
    """Atomically claim one pending outbox event and its judging attempt."""
    with SessionLocal() as db:
        event = db.execute(
            select(OutboxEvent)
            .where(
                OutboxEvent.published_at.is_(None),
                OutboxEvent.event_type == "submission.queued",
            )
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).scalar_one_or_none()

        if event is None:
            return None

        try:
            attempt_id = UUID(event.payload["attempt_id"])
        except (KeyError, ValueError, TypeError):
            logger.exception("Invalid attempt ID in outbox event %s", event.id)
            event.published_at = utc_now()
            db.commit()
            return None

        attempt = db.execute(
            select(JudgingAttempt)
            .where(JudgingAttempt.id == attempt_id)
            .with_for_update()
        ).scalar_one_or_none()

        if attempt is None or attempt.status != "queued":
            # This event no longer represents claimable work.
            event.published_at = utc_now()
            db.commit()
            return None

        submission = db.get(Submission, attempt.submission_id)

        if submission is None:
            event.published_at = utc_now()
            db.commit()
            return None

        token = uuid4().hex
        now = utc_now()

        attempt.status = "running"
        attempt.worker_token = token
        attempt.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        attempt.started_at = now

        submission.status = "running"
        event.published_at = now

        db.commit()

        logger.info(
            "Claimed submission=%s attempt=%s",
            submission.id,
            attempt.id,
        )

        return {
            "attempt_id": attempt.id,
            "submission_id": submission.id,
            "worker_token": token,
        }


def heartbeat(attempt_id, token, stop_event):
    """Extend the lease while this worker is executing the job."""
    while not stop_event.wait(HEARTBEAT_SECONDS):
        try:
            with SessionLocal() as db:
                result = db.execute(
                    update(JudgingAttempt)
                    .where(
                        JudgingAttempt.id == attempt_id,
                        JudgingAttempt.worker_token == token,
                        JudgingAttempt.status == "running",
                    )
                    .values(
                        lease_expires_at=utc_now()
                        + timedelta(seconds=LEASE_SECONDS)
                    )
                )
                db.commit()

                if result.rowcount != 1:
                    logger.warning("Lease lost for attempt %s", attempt_id)
                    return

        except Exception:
            logger.exception("Heartbeat failed for attempt %s", attempt_id)


def normalized_output(value):
    """Ignore harmless whitespace differences in judged output."""
    return " ".join(value.split())


def execute_submission(job, runner):
    """Run the submission against the immutable test-suite snapshot."""
    with SessionLocal() as db:
        attempt = db.get(JudgingAttempt, job["attempt_id"])
        submission = db.get(Submission, job["submission_id"])

        if attempt is None or submission is None:
            return {"verdict": "JUDGE_ERROR", "score": 0}

        problem_version = db.get(
            ProblemVersion,
            attempt.problem_version_id,
        )

        test_cases = db.execute(
            select(TestCase)
            .where(
                TestCase.test_suite_version_id
                == attempt.test_suite_version_id
            )
            .order_by(TestCase.position, TestCase.id)
        ).scalars().all()

        if problem_version is None or not test_cases:
            return {"verdict": "JUDGE_ERROR", "score": 0}

        source_code = submission.source_code
        time_limit_ms = problem_version.time_limit_ms
        memory_limit_mb = problem_version.memory_limit_mb
        points = problem_version.points

        # Copy the case data before closing the database session.
        cases = [
            (case.input_data, case.expected_output)
            for case in test_cases
        ]

    for input_data, expected_output in cases:
        result = runner.run(
            source_code=source_code,
            input_data=input_data,
            time_limit_ms=time_limit_ms,
            memory_limit_mb=memory_limit_mb,
        )

        verdict = result.get("verdict")

        if verdict == "JUDGE_ERROR":
            return {"verdict": "JUDGE_ERROR", "score": 0}

        if verdict == "CE":
            return {"verdict": "CE", "score": 0}

        if verdict == "TLE":
            return {"verdict": "TLE", "score": 0}

        if verdict == "OLE":
            return {"verdict": "OLE", "score": 0}

        if verdict == "RE":
            return {"verdict": "RE", "score": 0}

        if verdict != "OK":
            return {"verdict": "JUDGE_ERROR", "score": 0}

        if normalized_output(result.get("stdout", "")) != normalized_output(
            expected_output
        ):
            return {"verdict": "WA", "score": 0}

    return {"verdict": "AC", "score": points}


def save_result(job, result):
    """Persist results only if this worker still owns the attempt."""
    with SessionLocal() as db:
        attempt = db.execute(
            select(JudgingAttempt)
            .where(JudgingAttempt.id == job["attempt_id"])
            .with_for_update()
        ).scalar_one_or_none()

        if (
            attempt is None
            or attempt.status != "running"
            or attempt.worker_token != job["worker_token"]
            or not attempt.is_authoritative
        ):
            logger.warning(
                "Discarding stale result for attempt %s",
                job["attempt_id"],
            )
            return

        submission = db.get(Submission, attempt.submission_id)
        if submission is None:
            return

        now = utc_now()
        verdict = result["verdict"]

        if verdict == "JUDGE_ERROR" and attempt.retry_count < MAX_RETRIES:
            attempt.retry_count += 1
            attempt.status = "queued"
            attempt.worker_token = None
            attempt.lease_expires_at = None
            submission.status = "queued"

            event = db.execute(
                select(OutboxEvent)
                .where(OutboxEvent.event_key == event_key_for(attempt))
                .with_for_update()
            ).scalar_one_or_none()

            if event:
                event.published_at = None
            else:
                db.add(
                    OutboxEvent(
                        event_key=event_key_for(attempt),
                        event_type="submission.queued",
                        payload={
                            "submission_id": str(submission.id),
                            "attempt_id": str(attempt.id),
                            "attempt_number": attempt.attempt_number,
                        },
                    )
                )

            logger.warning(
                "Retrying judge error for attempt %s (%s/%s)",
                attempt.id,
                attempt.retry_count,
                MAX_RETRIES,
            )

        elif verdict == "JUDGE_ERROR":
            attempt.status = "failed"
            attempt.verdict = "JUDGE_ERROR"
            attempt.score = 0
            attempt.completed_at = now
            attempt.worker_token = None
            attempt.lease_expires_at = None
            submission.status = "failed"

            logger.error("Judge retries exhausted for %s", attempt.id)

        else:
            attempt.status = "completed"
            attempt.verdict = verdict
            attempt.score = result["score"]
            attempt.completed_at = now
            attempt.worker_token = None
            attempt.lease_expires_at = None
            submission.status = "completed"

            logger.info(
                "Judging complete submission=%s verdict=%s score=%s",
                submission.id,
                verdict,
                attempt.score,
            )

        db.commit()


def process_job(job, runner):
    stop_event = threading.Event()

    heartbeat_thread = threading.Thread(
        target=heartbeat,
        args=(job["attempt_id"], job["worker_token"], stop_event),
        daemon=True,
    )
    heartbeat_thread.start()

    try:
        result = execute_submission(job, runner)
        save_result(job, result)
    except Exception:
        logger.exception("Unexpected worker error for %s", job["attempt_id"])
        save_result(job, {"verdict": "JUDGE_ERROR", "score": 0})
    finally:
        stop_event.set()
        heartbeat_thread.join(timeout=2)


def main():
    logger.info("SHODH judge worker starting")

    runner = DockerPythonRunner()

    try:
        while True:
            try:
                recover_expired_attempts()
                job = claim_one()

                if job is None:
                    time.sleep(POLL_INTERVAL)
                    continue

                process_job(job, runner)

            except Exception:
                logger.exception("Worker loop error")
                time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        logger.info("Worker stopping")

    finally:
        runner.close()


if __name__ == "__main__":
    main()