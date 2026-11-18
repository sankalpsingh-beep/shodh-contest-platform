# SHODH — Contest Platform Backend

A backend contest platform with organization-based access control, contest/problem management, idempotent submissions, and asynchronous Docker-based judging.

## Technology
- Python / FastAPI
- PostgreSQL
- SQLAlchemy
- Alembic migrations
- JWT authentication
- Docker-based code execution
- Pytest
- Locust

## Architecture
- **API:** Authentication, organizations, contests, problems, participation, submissions, and leaderboard endpoints.
- **Database:** PostgreSQL relational persistence with migrations and indexes.
- **Worker:** Asynchronous submission processing through persisted attempts and outbox events.
- **Judge runner:** Executes submitted Python programs in constrained Docker containers.
- **Outbox/recovery:** Durable job records, retry attempts, leases, and recovery of expired work.

## Local setup
1. Copy `.env.example` to `.env` if provided, then configure database and JWT settings. Do not commit secrets.
2. Start the services:
   ```bash
   docker compose up --build -d
   ```
3. Apply migrations:
   ```bash
   docker compose exec api alembic upgrade head
   ```
4. Create demo accounts and organizations:
   ```bash
   docker compose exec api python seeds/seed_auth.py
   ```
5. API documentation:
   - Swagger UI: `http://localhost:8000/docs`
   - OpenAPI: `http://localhost:8000/openapi.json`

## Demo accounts
All demo accounts use the seed script's demo password: `ShodhDemo@2026`.

| Account | Organization | Role |
|---|---|---|
| organizer1@shodh.dev | Shodh Organization One | Organizer |
| participant1@shodh.dev | Shodh Organization One | Participant |
| organizer2@shodh.dev | Shodh Organization Two | Organizer |
| participant2@shodh.dev | Shodh Organization Two | Participant |

Use these accounts only in a local/demo environment. Change or remove demo credentials before deployment.

## API overview
Use Swagger UI (`/docs`) for request/response schemas.

- `POST /auth/token` — obtain JWT
- `GET /auth/me` — current identity
- `POST /organizations/{organization_id}/contests` — create contest (organizer)
- `GET /organizations/{organization_id}/contests` — list organization contests
- `GET /contests/{contest_id}` — contest details
- `POST /contests/{contest_id}/join` — join published contest (participant)
- `GET /contests/{contest_id}/leaderboard` — paginated leaderboard
- `POST /contests/{contest_id}/problems` — create problem (organizer)
- `GET /contests/{contest_id}/problems` — list problems
- `GET /problems/{problem_id}` — problem details
- `PUT /problems/{problem_id}` — create/update problem version
- `GET /problems/{problem_id}/test-cases` — organizer test cases
- `POST /contests/{contest_id}/problems/{problem_id}/submissions` — submit code
- `GET /submissions/{submission_id}` — submission status/result

Submission requests support an `Idempotency-Key` header. Submissions pin problem and test-suite versions so judging uses the versions associated with submission time.

## Judging
The worker processes persisted jobs asynchronously. Supported verdicts include:
- Accepted (AC)
- Wrong Answer (WA)
- Compilation Error (CE)
- Runtime Error (RE)
- Time Limit Exceeded (TLE)
- Output Limit Exceeded (OLE)
- Judge Error (JUDGE_ERROR)

The runner uses Docker isolation with network disabled, a non-root user, read-only container filesystem, resource limits, process limits, dropped capabilities, and bounded output. Worker containers need Docker access to launch user-code containers; submitted code containers do not receive the Docker socket.

## Tests
Run the test suite against the configured test database:
```powershell
docker compose exec -e PYTHONPATH=/app -e TEST_DATABASE_URL="postgresql+psycopg://shodh:shodh_dev_password@db:5432/shodh_test" api python -m pytest -v
```

The recorded suite result at the time of this README preparation was **15 passed**. Re-run tests against the final commit and include the new output in results.

## Load testing
Locust scenario: `locustfile.py`.

Recorded run:
- 20 concurrent users
- Ramp-up: 5 users/second
- Duration: 60 seconds
- Total requests: 804
- Failures: 0
- Throughput: 13.48 requests/second
- Average latency: 11 ms
- Median latency: 7 ms
- 95th percentile latency: 16 ms
- Maximum latency: 219 ms

Results are saved in `results/` (CSV files and summary). These are measurements from the tested environment and dataset, not a production capacity claim.

## Database indexes
The inspected database contained 27 indexes, including:
- `ix_contests_org_start`
- `ix_submissions_contest_user`
- `ix_attempts_status`
- `ix_outbox_pending`
- `uq_submission_idempotency`
- `uq_contest_participant`
- `uq_org_membership`

Query-plan observations are documented in `results/database-performance.md`.

## Repository layout
```text
app/
  api/        HTTP endpoints
  core/       configuration and security
  judge/      Docker runner
  models/     SQLAlchemy entities
  schemas/    request/response schemas
  workers/    asynchronous worker
migrations/   Alembic migrations
seeds/       demo data
tests/       unit/integration/security/concurrency tests
results/     saved test and performance evidence
locustfile.py
docker-compose.yml
Dockerfile
requirements.txt
```

## Known limitations / further work
- Add a dedicated rejudge workflow with explicit rejudge/version semantics.
- Expand load tests with a larger generated dataset and sustained/longer-duration runs.
- Add broader automated authorization coverage for every mutation and organization boundary.
- Add operational health checks, metrics, alerting, and production deployment hardening.
- Review worker/outbox lease handling and failure paths further before production use.

## AI assistance disclosure
AI assistance was used for development support, debugging, drafting documentation, and test/assessment workflow guidance. Implementation, local execution, and verification results should be reviewed and reported based on actual repository and test evidence.
