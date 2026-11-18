
from datetime import datetime, timedelta, timezone

from app.models import (
    JudgingAttempt,
    Organization,
    Problem,
    ProblemVersion,
    Submission,
    TestSuiteVersion as SuiteVersion,
)


def create_submission(
    db,
    user,
    contest,
    problem,
    problem_version,
    suite,
    score,
    completed_at,
    attempt_number,
):
    submission = Submission(
        contest_id=contest.id,
        problem_id=problem.id,
        problem_version_id=problem_version.id,
        test_suite_version_id=suite.id,
        user_id=user.id,
        idempotency_key=f"test-key-{user.id}-{attempt_number}",
        request_hash=f"test-hash-{user.id}-{attempt_number}",
        source_code="print(1)",
        language="python",
        runtime_config={},
        status="completed",
    )

    db.add(submission)
    db.flush()

    attempt = JudgingAttempt(
        submission_id=submission.id,
        attempt_number=attempt_number,
        problem_version_id=problem_version.id,
        test_suite_version_id=suite.id,
        status="completed",
        verdict="AC" if score > 0 else "WA",
        score=score,
        is_authoritative=True,
        completed_at=completed_at,
    )

    db.add(attempt)
    db.flush()

    return submission


def setup_leaderboard(
    db_session,
    create_user,
    create_organization,
    add_membership,
    create_contest,
    add_participant,
):
    org = create_organization("Test Organization", "test-org")
    participant1 = create_user(
        "leader1@test.dev", "Participant Alpha"
    )
    participant2 = create_user(
        "leader2@test.dev", "Participant Beta"
    )

    add_membership(participant1, org, "participant")
    add_membership(participant2, org, "participant")

    contest = create_contest(org, "Leaderboard Test")
    add_participant(participant1, contest)
    add_participant(participant2, contest)

    problem = Problem(
        contest_id=contest.id,
        slug="sum",
        title="Sum",
        current_version=1,
    )
    db_session.add(problem)
    db_session.flush()

    problem_version = ProblemVersion(
        problem_id=problem.id,
        version=1,
        statement="Add two numbers",
        input_description="Two numbers",
        output_description="Their sum",
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

    base_time = datetime.now(timezone.utc) - timedelta(minutes=10)

    # Participant Alpha submits twice.
    # Only their best score should count.
    create_submission(
        db_session, participant1, contest, problem,
        problem_version, suite, 50, base_time, 1
    )
    create_submission(
        db_session, participant1, contest, problem,
        problem_version, suite, 100,
        base_time + timedelta(minutes=2), 2
    )

    # Participant Beta has a score of 75.
    create_submission(
        db_session, participant2, contest, problem,
        problem_version, suite, 75,
        base_time + timedelta(minutes=3), 1
    )

    db_session.flush()

    return {
        "contest": contest,
        "participant1": participant1,
        "participant2": participant2,
    }


def test_leaderboard_uses_best_score(
    client,
    db_session,
    create_user,
    create_organization,
    add_membership,
    create_contest,
    add_participant,
    auth_headers,
):
    data = setup_leaderboard(
        db_session,
        create_user,
        create_organization,
        add_membership,
        create_contest,
        add_participant,
    )

    response = client.get(
        f"/contests/{data['contest'].id}/leaderboard",
        headers=auth_headers(data["participant1"]),
    )

    assert response.status_code == 200

    results = response.json()

    assert len(results) == 2
    assert results[0]["display_name"] == "Participant Alpha"
    assert results[0]["score"] == 100
    assert results[0]["rank"] == 1

    assert results[1]["display_name"] == "Participant Beta"
    assert results[1]["score"] == 75
    assert results[1]["rank"] == 2


def test_leaderboard_pagination_preserves_global_rank(
    client,
    db_session,
    create_user,
    create_organization,
    add_membership,
    create_contest,
    add_participant,
    auth_headers,
):
    data = setup_leaderboard(
        db_session,
        create_user,
        create_organization,
        add_membership,
        create_contest,
        add_participant,
    )

    url = f"/contests/{data['contest'].id}/leaderboard"
    headers = auth_headers(data["participant1"])

    page1 = client.get(
        url,
        params={"limit": 1, "offset": 0},
        headers=headers,
    )

    page2 = client.get(
        url,
        params={"limit": 1, "offset": 1},
        headers=headers,
    )

    assert page1.status_code == 200
    assert page2.status_code == 200

    assert page1.json()[0]["rank"] == 1
    assert page2.json()[0]["rank"] == 2


def test_leaderboard_blocks_other_organization(
    client,
    db_session,
    create_user,
    create_organization,
    add_membership,
    create_contest,
    add_participant,
    auth_headers,
):
    data = setup_leaderboard(
        db_session,
        create_user,
        create_organization,
        add_membership,
        create_contest,
        add_participant,
    )

    other_org = create_organization(
        "Other Organization", "other-org"
    )
    other_organizer = create_user(
        "other-organizer@test.dev",
        "Other Organizer",
    )

    add_membership(other_organizer, other_org, "organizer")

    response = client.get(
        f"/contests/{data['contest'].id}/leaderboard",
        headers=auth_headers(other_organizer),
    )

    assert response.status_code == 403
