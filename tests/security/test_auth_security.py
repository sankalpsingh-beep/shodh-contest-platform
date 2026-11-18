
def test_missing_token_returns_401(client):
    response = client.get("/auth/me")

    assert response.status_code == 401


def test_invalid_token_returns_401(client):
    response = client.get(
        "/auth/me",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 401


def test_inactive_user_returns_401(
    client,
    create_user,
    auth_headers,
):
    inactive_user = create_user(
        "inactive@test.dev",
        "Inactive User",
        is_active=False,
    )

    response = client.get(
        "/auth/me",
        headers=auth_headers(inactive_user),
    )

    assert response.status_code == 401


def test_participant_cannot_create_contest(
    client,
    create_user,
    create_organization,
    add_membership,
    auth_headers,
):
    participant = create_user(
        "participant-security@test.dev",
        "Security Participant",
    )

    organization = create_organization(
        "Security Organization",
        "security-org",
    )

    add_membership(participant, organization, "participant")

    response = client.post(
        f"/organizations/{organization.id}/contests",
        headers=auth_headers(participant),
        json={
            "title": "Unauthorized Contest",
            "description": "This should be rejected",
            "starts_at": "2026-11-18T10:00:00Z",
            "ends_at": "2026-11-18T12:00:00Z",
            "duration_minutes": 120,
            "is_published": True,
        },
    )

    assert response.status_code == 403
