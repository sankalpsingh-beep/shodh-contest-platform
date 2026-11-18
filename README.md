# SHODH — Contest Platform Backend

Backend contest platform supporting organization-scoped access, contest/problem management, versioned problem and test-suite data, idempotent submissions, asynchronous Docker judging, and leaderboard calculation.

## Stack
Python 3.12, FastAPI, PostgreSQL, SQLAlchemy, Alembic, JWT, Docker, Pytest, Locust.

## Architecture
- **API:** Authentication, contest/problem management, participation, submission creation/status, and leaderboard.
- **Database:** PostgreSQL; SQLAlchemy models and Alembic migrations.
- **Submission pipeline:** Submission, attempt, and outbox event are persisted transactionally; workers asynchronously claim and judge work.
- **Workers:** Multiple worker processes claim jobs using database coordination. Attempts use lease/token checks to prevent stale workers from persisting results.
- **Judge:** Submitted Python is run in a Docker container with network disabled, non-root execution, read-only filesystem, resource/process limits, dropped capabilities, no-new-privileges, and bounded output.
- **Recovery:** Expired running work is recovered and retried within the configured attempt limit. Final exhausted work is marked failed/JUDGE_ERROR.

## Setup
```powershell
docker compose up --build -d
docker compose exec api alembic upgrade head
docker compose exec api python seeds/seed_auth.py
```
Configure local environment values in `.env` (do not commit it). Swagger UI: `http://localhost:8000/docs`; OpenAPI: `http://localhost:8000/openapi.json`.

## Demo identities
Seed password for all accounts: `ShodhDemo@2026` (local/demo only).

| Email | Organization | Role |
|---|---|---|
| organizer1@shodh.dev | Shodh Organization One | organizer |
| participant1@shodh.dev | Shodh Organization One | participant |
| organizer2@shodh.dev | Shodh Organization Two | organizer |
| participant2@shodh.dev | Shodh Organization Two | participant |

## Authorization rules
- Users must authenticate with a valid JWT and be active.
- Organization-scoped endpoints require membership in the target organization.
- Organizer membership is required for contest/problem creation and problem updates, and for access to hidden test cases.
- Participants may join published contests and submit only when joined and within contest rules/time window.
- Participants cannot view unpublished contests or hidden test cases.
- Submission status/source access is restricted to its owner and authorized contest organizers.
- Cross-organization access is rejected.

## API endpoints
- `POST /auth/token` — issue token
- `GET /auth/me` — current identity
- `POST /organizations/{organization_id}/contests` — organizer creates contest
- `GET /organizations/{organization_id}/contests` — organization contest list
- `GET /contests/{contest_id}` — contest detail
- `POST /contests/{contest_id}/join` — participant joins published contest
- `GET /contests/{contest_id}/leaderboard` — paginated leaderboard
- `POST /contests/{contest_id}/problems` — organizer creates problem
- `GET /contests/{contest_id}/problems` — problem list; samples only
- `GET /problems/{problem_id}` — problem detail
- `PUT /problems/{problem_id}` — create a new problem version
- `GET /problems/{problem_id}/test-cases` — organizer-only test cases
- `POST /contests/{contest_id}/problems/{problem_id}/submissions` — submit code
- `GET /submissions/{submission_id}` — submission status/result

Use `/docs` for full request/response schemas and interactive examples.

## Submission and attempt state model
**Submission:** `queued → running → completed` or `queued/running → failed` after exhausted infrastructure retries.

**Judging attempt:** `queued → running → completed` or `running → failed`; expired running attempts can be recovered/retried. Attempts are numbered per submission. Lease/token checks fence stale workers. The submission records the authoritative final outcome; a stale attempt cannot overwrite it.

Submission creation accepts an `Idempotency-Key`. Repeating the same key and payload returns the existing submission; reusing the key with a different payload returns HTTP 409. Submission pins problem-version and test-suite-version IDs at creation time.

## Scoring and leaderboard
- A participant's score is derived from their best completed authoritative attempt for each problem.
- Per-problem scores are aggregated for contest total.
- Participants with zero score remain eligible to appear.
- Leaderboard pagination preserves global rank.
- Ordering is deterministic: higher total score first; ties use the earliest achievement of that score, with stable participant ordering as a final tie-breaker.
- Failed/infrastructure attempts do not count as accepted scoring attempts.

## Verdicts
AC (Accepted), WA (Wrong Answer), CE (Compilation Error), RE (Runtime Error), TLE (Time Limit Exceeded), OLE (Output Limit Exceeded), JUDGE_ERROR (judge/infrastructure failure).

## Functional evaluation
Run:
```powershell
docker compose exec -e PYTHONPATH=/app -e TEST_DATABASE_URL="postgresql+psycopg://shodh:shodh_dev_password@db:5432/shodh_test" api python -m pytest -v
```
Recorded final run: **15 passed** (one third-party deprecation warning).

## Concurrent evaluation
Concurrency tests:
```powershell
docker compose exec -e PYTHONPATH=/app -e TEST_DATABASE_URL="postgresql+psycopg://shodh:shodh_dev_password@db:5432/shodh_test" api python -m pytest -v tests/concurrency
```
These tests coordinate worker claims/recovery using controlled synchronization and verify final persistent state, including duplicate claim prevention, stale-worker fencing, lease recovery, and retry exhaustion. They exercise worker coordination against shared persistent storage.

## Load test
Locust file: `locustfile.py`. Recorded run (20 users, 5 users/sec ramp, 60 seconds):
```powershell
docker compose exec api python -m locust -f /app/locustfile.py --headless -u 20 -r 5 --run-time 1m --host http://localhost:8000 --csv /app/results/locust
```
Results: 804 requests, 0 failures, 13.48 requests/sec, average 11 ms, median 7 ms, P95 16 ms, max 219 ms. Endpoint CSVs are saved in `results/`. This was a read-heavy workload and is not a production capacity claim.

## Database performance evidence
Database contained 27 indexes. The contest-by-organization query used `ix_contests_org_start` (Index Scan, 0.049 ms). Submission lookup and queued-attempt query used sequential scans on the small dataset (0.030 ms and 0.015 ms). See `results/database-performance.md`.

## Repository layout
`app/` application code; `migrations/` schema migration; `seeds/` demo seed; `tests/` integration/security/concurrency; `results/` saved evidence; `reports/` engineering report.

## Known limitations
- Rejudge workflow and explicit rejudge/version semantics are not implemented.
- Load test is short and read-heavy; larger dataset, write-path and sustained tests remain.
- Broader route-by-route authorization coverage remains future work.
- Operational health checks, metrics, alerting and deployment hardening remain.
- Worker/outbox exception and lease edge cases merit further review.

## AI assistance
See `ai-assistance-disclosure.md`.
