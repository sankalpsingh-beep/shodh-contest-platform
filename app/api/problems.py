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
    Problem,
    ProblemVersion,
    TestSuiteVersion,
    TestCase,
    User,
)
from app.schemas.problem import (
    ProblemCreate,
    ProblemUpdate,
    ProblemResponse,
    ProblemCreatedResponse,
    OrganizerTestCaseResponse,
)

router = APIRouter(tags=["Problems"])


def get_membership(db: Session, user_id: UUID, organization_id: UUID):
    return db.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.organization_id == organization_id,
        )
    ).scalar_one_or_none()


def get_problem_context(db: Session, problem_id: UUID):
    result = db.execute(
        select(Problem, Contest)
        .join(Contest, Problem.contest_id == Contest.id)
        .where(Problem.id == problem_id)
    ).first()

    if result is None:
        raise HTTPException(status_code=404, detail="Problem not found")

    return result[0], result[1]


def check_problem_access(db: Session, user: User, contest: Contest):
    membership = get_membership(db, user.id, contest.organization_id)

    if membership is None:
        raise HTTPException(
            status_code=403,
            detail="You are not a member of this organization",
        )

    if membership.role == "organizer":
        return membership

    if not contest.is_published:
        raise HTTPException(status_code=404, detail="Problem not found")

    participation = db.execute(
        select(Participation).where(
            Participation.contest_id == contest.id,
            Participation.user_id == user.id,
        )
    ).scalar_one_or_none()

    if participation is None:
        raise HTTPException(
            status_code=403,
            detail="Join the contest before viewing its problems",
        )

    return membership


def get_current_problem_version(db: Session, problem: Problem):
    version = db.execute(
        select(ProblemVersion).where(
            ProblemVersion.problem_id == problem.id,
            ProblemVersion.version == problem.current_version,
        )
    ).scalar_one_or_none()

    if version is None:
        raise HTTPException(status_code=404, detail="Problem version not found")

    suite = db.execute(
        select(TestSuiteVersion).where(
            TestSuiteVersion.problem_version_id == version.id
        ).order_by(TestSuiteVersion.version.desc())
    ).scalars().first()

    if suite is None:
        raise HTTPException(status_code=404, detail="Test suite not found")

    return version, suite


def build_problem_response(db: Session, problem: Problem):
    version, suite = get_current_problem_version(db, problem)

    samples = db.execute(
        select(TestCase)
        .where(
            TestCase.test_suite_version_id == suite.id,
            TestCase.is_hidden.is_(False),
        )
        .order_by(TestCase.position.asc())
    ).scalars().all()

    return ProblemResponse(
        id=problem.id,
        contest_id=problem.contest_id,
        slug=problem.slug,
        title=version.statement and problem.title,
        version=version.version,
        statement=version.statement,
        input_description=version.input_description,
        output_description=version.output_description,
        points=version.points,
        time_limit_ms=version.time_limit_ms,
        memory_limit_mb=version.memory_limit_mb,
        sample_test_cases=[
            {
                "input": case.input_data,
                "expected_output": case.expected_output,
            }
            for case in samples
        ],
    )


@router.post(
    "/contests/{contest_id}/problems",
    response_model=ProblemCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_problem(
    contest_id: UUID,
    payload: ProblemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    contest = db.get(Contest, contest_id)

    if contest is None:
        raise HTTPException(status_code=404, detail="Contest not found")

    membership = get_membership(db, user.id, contest.organization_id)

    if membership is None or membership.role != "organizer":
        raise HTTPException(
            status_code=403,
            detail="Only organization organizers can create problems",
        )

    problem = Problem(
        contest_id=contest.id,
        slug=payload.slug,
        title=payload.title,
        current_version=1,
    )
    db.add(problem)

    try:
        db.flush()

        version = ProblemVersion(
            problem_id=problem.id,
            version=1,
            statement=payload.statement,
            input_description=payload.input_description,
            output_description=payload.output_description,
            points=payload.points,
            time_limit_ms=payload.time_limit_ms,
            memory_limit_mb=payload.memory_limit_mb,
        )
        db.add(version)
        db.flush()

        suite = TestSuiteVersion(
            problem_version_id=version.id,
            version=1,
        )
        db.add(suite)
        db.flush()

        for position, case in enumerate(payload.test_cases, start=1):
            db.add(
                TestCase(
                    test_suite_version_id=suite.id,
                    position=position,
                    input_data=case.input_data,
                    expected_output=case.expected_output,
                    is_hidden=case.is_hidden,
                )
            )

        db.commit()
        db.refresh(problem)

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A problem with this slug already exists in the contest",
        )

    return ProblemCreatedResponse(
        id=problem.id,
        slug=problem.slug,
        title=problem.title,
        version=1,
        test_case_count=len(payload.test_cases),
    )


@router.get(
    "/contests/{contest_id}/problems",
    response_model=list[ProblemResponse],
)
def list_problems(
    contest_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    contest = db.get(Contest, contest_id)

    if contest is None:
        raise HTTPException(status_code=404, detail="Contest not found")

    check_problem_access(db, user, contest)

    problems = db.execute(
        select(Problem)
        .where(Problem.contest_id == contest.id)
        .order_by(Problem.slug.asc(), Problem.id.asc())
    ).scalars().all()

    return [
        build_problem_response(db, problem)
        for problem in problems
    ]


@router.get(
    "/problems/{problem_id}",
    response_model=ProblemResponse,
)
def get_problem(
    problem_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    problem, contest = get_problem_context(db, problem_id)
    check_problem_access(db, user, contest)
    return build_problem_response(db, problem)


@router.put(
    "/problems/{problem_id}",
    response_model=ProblemCreatedResponse,
)
def update_problem(
    problem_id: UUID,
    payload: ProblemUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    problem, contest = get_problem_context(db, problem_id)

    membership = get_membership(db, user.id, contest.organization_id)

    if membership is None or membership.role != "organizer":
        raise HTTPException(
            status_code=403,
            detail="Only organization organizers can update problems",
        )

    try:
        # Lock the problem row to prevent concurrent version-number collisions.
        problem = db.execute(
            select(Problem)
            .where(Problem.id == problem_id)
            .with_for_update()
        ).scalar_one()

        next_version = problem.current_version + 1

        version = ProblemVersion(
            problem_id=problem.id,
            version=next_version,
            statement=payload.statement,
            input_description=payload.input_description,
            output_description=payload.output_description,
            points=payload.points,
            time_limit_ms=payload.time_limit_ms,
            memory_limit_mb=payload.memory_limit_mb,
        )
        db.add(version)
        db.flush()

        suite = TestSuiteVersion(
            problem_version_id=version.id,
            version=1,
        )
        db.add(suite)
        db.flush()

        for position, case in enumerate(payload.test_cases, start=1):
            db.add(
                TestCase(
                    test_suite_version_id=suite.id,
                    position=position,
                    input_data=case.input_data,
                    expected_output=case.expected_output,
                    is_hidden=case.is_hidden,
                )
            )

        problem.title = payload.title
        problem.current_version = next_version
        db.commit()
        db.refresh(problem)

    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Problem version conflict")

    return ProblemCreatedResponse(
        id=problem.id,
        slug=problem.slug,
        title=problem.title,
        version=next_version,
        test_case_count=len(payload.test_cases),
    )


@router.get(
    "/problems/{problem_id}/test-cases",
    response_model=list[OrganizerTestCaseResponse],
)
def get_all_test_cases(
    problem_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    problem, contest = get_problem_context(db, problem_id)

    membership = get_membership(db, user.id, contest.organization_id)

    if membership is None or membership.role != "organizer":
        raise HTTPException(
            status_code=403,
            detail="Only organization organizers can view hidden test cases",
        )

    version, suite = get_current_problem_version(db, problem)

    cases = db.execute(
        select(TestCase)
        .where(TestCase.test_suite_version_id == suite.id)
        .order_by(TestCase.position.asc())
    ).scalars().all()

    return [
        OrganizerTestCaseResponse(
            position=case.position,
            input_data=case.input_data,
            expected_output=case.expected_output,
            is_hidden=case.is_hidden,
        )
        for case in cases
    ]
