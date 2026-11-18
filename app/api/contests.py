
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.models import (
    Contest,
    JudgingAttempt,
    OrganizationMembership,
    Participation,
    Submission,
    User,
)
from app.schemas.contest import (
    ContestCreate,
    ContestResponse,
    MessageResponse,
)
from app.schemas.leaderboard import LeaderboardEntry

router = APIRouter(tags=["Contests"])


def get_membership(
    db: Session,
    user_id: UUID,
    organization_id: UUID,
):
    return db.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.organization_id == organization_id,
        )
    ).scalar_one_or_none()


def get_contest_or_404(db: Session, contest_id: UUID):
    contest = db.get(Contest, contest_id)

    if contest is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contest not found",
        )

    return contest


@router.post(
    "/organizations/{organization_id}/contests",
    response_model=ContestResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_contest(
    organization_id: UUID,
    payload: ContestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    membership = get_membership(db, user.id, organization_id)

    if membership is None or membership.role != "organizer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organization organizers can create contests",
        )

    contest = Contest(
        organization_id=organization_id,
        title=payload.title,
        description=payload.description,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        duration_minutes=payload.duration_minutes,
        is_published=payload.is_published,
    )

    db.add(contest)
    db.commit()
    db.refresh(contest)

    return contest


@router.get(
    "/organizations/{organization_id}/contests",
    response_model=list[ContestResponse],
)
def list_contests(
    organization_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    membership = get_membership(db, user.id, organization_id)

    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this organization",
        )

    query = select(Contest).where(
        Contest.organization_id == organization_id
    )

    if membership.role == "participant":
        query = query.where(Contest.is_published.is_(True))

    query = query.order_by(
        Contest.starts_at.asc(),
        Contest.id.asc(),
    )

    return list(db.execute(query).scalars().all())


@router.get(
    "/contests/{contest_id}",
    response_model=ContestResponse,
)
def get_contest(
    contest_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    contest = get_contest_or_404(db, contest_id)

    membership = get_membership(
        db,
        user.id,
        contest.organization_id,
    )

    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this organization",
        )

    if membership.role == "participant" and not contest.is_published:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contest not found",
        )

    return contest


@router.post(
    "/contests/{contest_id}/join",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
def join_contest(
    contest_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    contest = get_contest_or_404(db, contest_id)

    membership = get_membership(
        db,
        user.id,
        contest.organization_id,
    )

    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this organization",
        )

    if membership.role != "participant":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only participants can join contests",
        )

    if not contest.is_published:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This contest is not published",
        )

    existing = db.execute(
        select(Participation).where(
            Participation.contest_id == contest.id,
            Participation.user_id == user.id,
        )
    ).scalar_one_or_none()

    if existing:
        return MessageResponse(
            message="Already registered for this contest"
        )

    participation = Participation(
        contest_id=contest.id,
        user_id=user.id,
    )

    db.add(participation)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return MessageResponse(
            message="Already registered for this contest"
        )

    return MessageResponse(
        message="Successfully joined the contest"
    )


@router.get(
    "/contests/{contest_id}/leaderboard",
    response_model=list[LeaderboardEntry],
)
def get_leaderboard(
    contest_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    contest = get_contest_or_404(db, contest_id)

    membership = get_membership(
        db,
        user.id,
        contest.organization_id,
    )

    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this organization",
        )

    if membership.role == "participant" and not contest.is_published:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contest not found",
        )

    # Rank completed, authoritative attempts for each problem.
    # The highest score per participant/problem is retained.
    ranked_attempts = (
        select(
            Submission.user_id.label("user_id"),
            Submission.problem_id.label("problem_id"),
            JudgingAttempt.score.label("score"),
            JudgingAttempt.completed_at.label("completed_at"),
            func.row_number().over(
                partition_by=(
                    Submission.user_id,
                    Submission.problem_id,
                ),
                order_by=(
                    JudgingAttempt.score.desc(),
                    JudgingAttempt.completed_at.asc(),
                    JudgingAttempt.id.asc(),
                ),
            ).label("attempt_rank"),
        )
        .join(
            JudgingAttempt,
            JudgingAttempt.submission_id == Submission.id,
        )
        .where(
            Submission.contest_id == contest.id,
            JudgingAttempt.status == "completed",
            JudgingAttempt.is_authoritative.is_(True),
            JudgingAttempt.completed_at.is_not(None),
        )
        .subquery()
    )

    # Retain only the best attempt for each problem.
    best_attempts = (
        select(
            ranked_attempts.c.user_id,
            ranked_attempts.c.score,
            ranked_attempts.c.completed_at,
        )
        .where(ranked_attempts.c.attempt_rank == 1)
        .subquery()
    )

    # Calculate total score and final-score achievement time.
    participant_totals = (
        select(
            best_attempts.c.user_id,
            func.sum(best_attempts.c.score).label("total_score"),
            func.max(best_attempts.c.completed_at).label(
                "last_improved_at"
            ),
        )
        .group_by(best_attempts.c.user_id)
        .subquery()
    )

    score_expression = func.coalesce(
        participant_totals.c.total_score,
        0,
    )

    # Include all registered participants, including those with zero scores.
    leaderboard_data = (
        select(
            User.id.label("user_id"),
            User.display_name.label("display_name"),
            score_expression.label("score"),
            participant_totals.c.last_improved_at,
        )
        .select_from(Participation)
        .join(
            User,
            User.id == Participation.user_id,
        )
        .outerjoin(
            participant_totals,
            participant_totals.c.user_id == User.id,
        )
        .where(
            Participation.contest_id == contest.id
        )
        .subquery()
    )

    # Calculate global ranks before applying pagination.
    ranked_leaderboard = (
        select(
            leaderboard_data.c.user_id,
            leaderboard_data.c.display_name,
            leaderboard_data.c.score,
            leaderboard_data.c.last_improved_at,
            func.row_number().over(
                order_by=(
                    leaderboard_data.c.score.desc(),
                    leaderboard_data.c.last_improved_at.asc().nulls_last(),
                    leaderboard_data.c.display_name.asc(),
                    leaderboard_data.c.user_id.asc(),
                )
            ).label("rank"),
        )
        .subquery()
    )

    # Apply pagination after global ranking.
    rows = db.execute(
        select(ranked_leaderboard)
        .order_by(ranked_leaderboard.c.rank)
        .offset(offset)
        .limit(limit)
    ).all()

    return [
        LeaderboardEntry(
            rank=row.rank,
            user_id=row.user_id,
            display_name=row.display_name,
            score=row.score,
            last_improved_at=row.last_improved_at,
        )
        for row in rows
    ]
