from app.database import SessionLocal
from app.models import User, Organization, OrganizationMembership
from app.core.security import hash_password

db = SessionLocal()

accounts = [
    {
        "email": "organizer1@shodh.dev",
        "name": "Organizer One",
        "org_name": "Shodh Organization One",
        "org_slug": "shodh-org-one",
        "role": "organizer",
    },
    {
        "email": "participant1@shodh.dev",
        "name": "Participant One",
        "org_name": "Shodh Organization One",
        "org_slug": "shodh-org-one",
        "role": "participant",
    },
    {
        "email": "organizer2@shodh.dev",
        "name": "Organizer Two",
        "org_name": "Shodh Organization Two",
        "org_slug": "shodh-org-two",
        "role": "organizer",
    },
    {
        "email": "participant2@shodh.dev",
        "name": "Participant Two",
        "org_name": "Shodh Organization Two",
        "org_slug": "shodh-org-two",
        "role": "participant",
    },
]

try:
    organizations = {}

    for item in accounts:
        org = db.query(Organization).filter(
            Organization.slug == item["org_slug"]
        ).first()

        if org is None:
            org = Organization(
                name=item["org_name"],
                slug=item["org_slug"],
            )
            db.add(org)
            db.flush()

        organizations[item["org_slug"]] = org

        user = db.query(User).filter(
            User.email == item["email"]
        ).first()

        if user is None:
            user = User(
                email=item["email"],
                display_name=item["name"],
                password_hash=hash_password("ShodhDemo@2026"),
                is_active=True,
            )
            db.add(user)
            db.flush()

        membership = db.query(OrganizationMembership).filter_by(
            organization_id=org.id,
            user_id=user.id,
        ).first()

        if membership is None:
            db.add(
                OrganizationMembership(
                    organization_id=org.id,
                    user_id=user.id,
                    role=item["role"],
                )
            )

    db.commit()
    print("Demo organizations and accounts created successfully.")

finally:
    db.close()
