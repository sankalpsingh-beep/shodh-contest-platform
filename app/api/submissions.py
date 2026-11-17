import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.models import (
    Contest,
    OrganizationMembership,
    Participation,
    Problem,
    ProblemVersion,
    TestSuiteVersion,
    Submission,
    JudgingAttempt,
    OutboxEvent,
    User,
)
from app.schemas.submission import (
    SubmissionCreate,
    SubmissionAcceptedResponse,
    SubmissionDetailResponse,
)

router = APIRouter(tags=["Submissions"])


def make_request_hash(problem_id: UUID, payload: SubmissionCreate) -> str:
    canonical = json.dumps(
        {
            "problem_id": str(problem_id),
            "language": payload.language,
            "source_code": payload.source_code,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_existing_submission(
    db: Session,
    contest_id: UUID,
    user_id: UUID,
    idempotency_key: str,
):
    return db.execute(
        select(Submission).where(
            Submission.contest_id == contest_id,
            Submission.user_id == user_id,
            Submission.idempotency_key == idempotency_key,
        )
    ).scalar_one_or_none()


def submission_response(submission: Submission):
    return SubmissionAcceptedResponse(
        id=submission.id,
        contest_id=submission.contest_id,
        problem_id=submission.problem_id,
        problem_version_id=submission.problem_version_id,
        test_suite_version_id=submission.test_suite_version_id,
        status=submission.status,
        created_at=submission.created_at,
        message="Submission accepted and queued for judging",
    )


@router.post(
    "/contests/{contest_id}/problems/{problem_id}/submissions",
    response_model=SubmissionAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_submission(
    contest_id: UUID,
    problem_id: UUID,
    payload: SubmissionCreate,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", idempotency_key):
        raise HTTPException(
            status_code=422,
            detail="Idempotency-Key must be 8-128 characters using letters, numbers, '.', '_', ':', or '-'",
        )

    contest = db.get(Contest, contest_id)
    if contest is None or not contest.is_published:
        raise HTTPException(status_code=404, detail="Contest not found")

    membership = db.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == contest.organization_id,
            OrganizationMembership.user_id == user.id,
        )
    ).scalar_one_or_none()

    if membership is None or membership.role != "participant":
        raise HTTPException(
            status_code=403,
            detail="Only organization participants can submit solutions",
        )

    participation = db.execute(
        select(Participation).where(
            Participation.contest_id == contest.id,
            Participation.user_id == user.id,
        )
    ).scalar_one_or_none()

    if participation is None:
        raise HTTPException(
            status_code=403,
            detail="Join the contest before submitting a solution",
        )

    now = datetime.now(timezone.utc)
    if now < contest.starts_at or now > contest.ends_at:
        raise HTTPException(
            status_code=400,
            detail="Submissions are allowed only during the contest window",
        )

    problem = db.execute(
        select(Problem).where(
            Problem.id == problem_id,
            Problem.contest_id == contest.id,
        )
    ).scalar_one_or_none()

    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found")

    problem_version = db.execute(
        select(ProblemVersion).where(
            ProblemVersion.problem_id == problem.id,
            ProblemVersion.version == problem.current_version,
        )
    ).scalar_one_or_none()

    if problem_version is None:
        raise HTTPException(status_code=409, detail="Current problem version not found")

    test_suite = db.execute(
        select(TestSuiteVersion)
        .where(TestSuiteVersion.problem_version_id == problem_version.id)
        .order_by(TestSuiteVersion.version.desc())
    ).scalars().first()

    if test_suite is None:
        raise HTTPException(status_code=409, detail="Test suite version not found")

    request_hash = make_request_hash(problem.id, payload)

    existing = get_existing_submission(
        db, contest.id, user.id, idempotency_key
    )

    if existing is not None:
        if existing.request_hash != request_hash:
            raise HTTPException(
                status_code=409,
                detail="This idempotency key was already used with a different submission",
            )
        return submission_response(existing)

    submission = Submission(
        contest_id=contest.id,
        problem_id=problem.id,
        problem_version_id=problem_version.id,
        test_suite_version_id=test_suite.id,
        user_id=user.id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        source_code=payload.source_code,
        language=payload.language,
        runtime_config={},
        status="queued",
    )
    db.add(submission)

    try:
        db.flush()

        attempt = JudgingAttempt(
            submission_id=submission.id,
            attempt_number=1,
            problem_version_id=problem_version.id,
            test_suite_version_id=test_suite.id,
            status="queued",
            score=0,
            is_authoritative=True,
            retry_count=0,
        )
        db.add(attempt)
        db.flush()

        event = OutboxEvent(
            event_key=f"judge:{submission.id}:attempt:1",
            event_type="submission.queued",
            payload={
                "submission_id": str(submission.id),
                "attempt_id": str(attempt.id),
                "attempt_number": 1,
            },
        )
        db.add(event)

        db.commit()
        db.refresh(submission)

    except IntegrityError:
        db.rollback()

        # A concurrent request may have inserted the same idempotency key.
        existing = get_existing_submission(
            db, contest.id, user.id, idempotency_key
        )

        if existing is not None and existing.request_hash == request_hash:
            return submission_response(existing)

        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail="This idempotency key was already used with a different submission",
            )

        raise HTTPException(
            status_code=409,
            detail="Submission conflicted with another request; retry with the same idempotency key",
        )

    return submission_response(submission)


@router.get(
    "/submissions/{submission_id}",
    response_model=SubmissionDetailResponse,
)
def get_submission(
    submission_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = db.execute(
        select(Submission, Contest)
        .join(Contest, Submission.contest_id == Contest.id)
        .where(Submission.id == submission_id)
    ).first()

    if result is None:
        raise HTTPException(status_code=404, detail="Submission not found")

    submission, contest = result

    is_owner = submission.user_id == user.id

    membership = db.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == contest.organization_id,
            OrganizationMembership.user_id == user.id,
        )
    ).scalar_one_or_none()

    is_organizer = membership is not None and membership.role == "organizer"

    if not is_owner and not is_organizer:
        raise HTTPException(status_code=404, detail="Submission not found")

    attempt = db.execute(
        select(JudgingAttempt)
        .where(JudgingAttempt.submission_id == submission.id)
        .order_by(JudgingAttempt.attempt_number.desc())
    ).scalars().first()

    return SubmissionDetailResponse(
        id=submission.id,
        contest_id=submission.contest_id,
        problem_id=submission.problem_id,
        problem_version_id=submission.problem_version_id,
        test_suite_version_id=submission.test_suite_version_id,
        language=submission.language,
        status=submission.status,
        created_at=submission.created_at,
        attempt_number=attempt.attempt_number if attempt else None,
        attempt_status=attempt.status if attempt else None,
        verdict=attempt.verdict if attempt else None,
        score=attempt.score if attempt else None,
    )


