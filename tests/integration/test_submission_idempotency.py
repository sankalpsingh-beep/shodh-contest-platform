
from sqlalchemy import func, select

from app.models import (
    JudgingAttempt,
    OutboxEvent,
    Problem,
    ProblemVersion,
    Submission,
    TestSuiteVersion as SuiteVersion,
)


def setup_submission_data(
    db_session,
    create_user,
    create_organization,
    add_membership,
    create_contest,
    add_participant,
):
    organization = create_organization(
        "Submission Test Org",
        "submission-test-org",
    )

    participant = create_user(
        "submission-user@test.dev",
        "Submission User",
    )

    add_membership(
        participant,
        organization,
        "participant",
    )

    contest = create_contest(
        organization,
        "Submission Idempotency Test",
    )

    add_participant(
        participant,
        contest,
    )

    problem = Problem(
        contest_id=contest.id,
        slug="test-problem",
        title="Test Problem",
        current_version=1,
    )

    db_session.add(problem)
    db_session.flush()

    problem_version = ProblemVersion(
        problem_id=problem.id,
        version=1,
        statement="Print the input",
        input_description="One input",
        output_description="One output",
        points=100,
        time_limit_ms=2000,
        memory_limit_mb=256,
    )

    db_session.add(problem_version)
    db_session.flush()

    suite = SuiteVersion(
        problem_version_id=problem_version.id,
        version=1,
    )

    db_session.add(suite)
    db_session.flush()

    return participant, contest, problem


def submit(
    client,
    participant,
    contest,
    problem,
    auth_headers,
    key,
    source_code="print(input())",
):
    return client.post(
        f"/contests/{contest.id}/problems/{problem.id}/submissions",
        headers={
            **auth_headers(participant),
            "Idempotency-Key": key,
        },
        json={
            "source_code": source_code,
            "language": "python",
        },
    )


def test_same_key_and_payload_returns_same_submission(
    client,
    db_session,
    create_user,
    create_organization,
    add_membership,
    create_contest,
    add_participant,
    auth_headers,
):
    participant, contest, problem = setup_submission_data(
        db_session,
        create_user,
        create_organization,
        add_membership,
        create_contest,
        add_participant,
    )

    first = submit(
        client,
        participant,
        contest,
        problem,
        auth_headers,
        "same-key-001",
    )

    second = submit(
        client,
        participant,
        contest,
        problem,
        auth_headers,
        "same-key-001",
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] == second.json()["id"]

    submission_id = first.json()["id"]

    submission_count = db_session.scalar(
        select(func.count())
        .select_from(Submission)
        .where(
            Submission.contest_id == contest.id
        )
    )

    attempt_count = db_session.scalar(
        select(func.count())
        .select_from(JudgingAttempt)
        .where(
            JudgingAttempt.submission_id.in_(
                select(Submission.id).where(
                    Submission.contest_id == contest.id
                )
            )
        )
    )

    event_count = db_session.scalar(
        select(func.count())
        .select_from(OutboxEvent)
        .where(
            OutboxEvent.event_key
            == f"judge:{submission_id}:attempt:1"
        )
    )

    assert submission_count == 1
    assert attempt_count == 1
    assert event_count == 1


def test_same_key_with_different_payload_returns_409(
    client,
    db_session,
    create_user,
    create_organization,
    add_membership,
    create_contest,
    add_participant,
    auth_headers,
):
    participant, contest, problem = setup_submission_data(
        db_session,
        create_user,
        create_organization,
        add_membership,
        create_contest,
        add_participant,
    )

    first = submit(
        client,
        participant,
        contest,
        problem,
        auth_headers,
        "conflict-key-001",
        "print(1)",
    )

    second = submit(
        client,
        participant,
        contest,
        problem,
        auth_headers,
        "conflict-key-001",
        "print(2)",
    )

    assert first.status_code == 202
    assert second.status_code == 409


def test_different_keys_create_separate_submissions(
    client,
    db_session,
    create_user,
    create_organization,
    add_membership,
    create_contest,
    add_participant,
    auth_headers,
):
    participant, contest, problem = setup_submission_data(
        db_session,
        create_user,
        create_organization,
        add_membership,
        create_contest,
        add_participant,
    )

    first = submit(
        client,
        participant,
        contest,
        problem,
        auth_headers,
        "different-key-001",
    )

    second = submit(
        client,
        participant,
        contest,
        problem,
        auth_headers,
        "different-key-002",
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] != second.json()["id"]


def test_missing_idempotency_key_returns_422(
    client,
    db_session,
    create_user,
    create_organization,
    add_membership,
    create_contest,
    add_participant,
    auth_headers,
):
    participant, contest, problem = setup_submission_data(
        db_session,
        create_user,
        create_organization,
        add_membership,
        create_contest,
        add_participant,
    )

    response = client.post(
        f"/contests/{contest.id}/problems/{problem.id}/submissions",
        headers=auth_headers(participant),
        json={
            "source_code": "print(input())",
            "language": "python",
        },
    )

    assert response.status_code == 422
