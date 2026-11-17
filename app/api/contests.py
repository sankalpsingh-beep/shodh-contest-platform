from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.models import (
    Contest,
    OrganizationMembership,
    Participation,
    User,
)
from app.schemas.contest import (
    ContestCreate,
    ContestResponse,
    MessageResponse,
)

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

    query = query.order_by(Contest.starts_at.asc(), Contest.id.asc())
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
        db, user.id, contest.organization_id
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
        db, user.id, contest.organization_id
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
        return MessageResponse(message="Already registered for this contest")

    participation = Participation(
        contest_id=contest.id,
        user_id=user.id,
    )
    db.add(participation)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return MessageResponse(message="Already registered for this contest")

    return MessageResponse(message="Successfully joined the contest")
