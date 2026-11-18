# SHODH Contest Platform — Engineering Report

## 1. Overview and architecture
SHODH is a FastAPI/PostgreSQL contest backend with JWT authentication, organization membership/roles, contests, participation, versioned problems/test suites, submissions, asynchronous judging, and leaderboards. SQLAlchemy models and Alembic migrations manage relational persistence. Submission creation stores the submission, judging attempt, and outbox event transactionally. Workers claim persisted work using database coordination, leases, and fencing tokens. Submissions pin problem and test-suite versions.

## 2. State, transaction and scoring behavior
Submission lifecycle: queued → running → completed; infrastructure retries can end in failed after the configured retry limit. Attempts are numbered and track their own state. Expired running attempts can be recovered. Lease/token checks prevent stale workers from persisting results. Idempotency keys prevent duplicate submissions: same key/payload returns the existing submission; same key/different payload returns 409.

Leaderboard uses best completed authoritative attempt per problem, aggregates problem scores, includes zero-score participants, and preserves global rank during pagination. Ordering is deterministic: score descending, earliest achievement for ties, with a stable final ordering.

Authorization is organization-scoped: active authenticated users require membership; organizer-only contest/problem mutations and hidden test-case access are enforced; participants join published contests before submitting; cross-organization access is rejected; submission access is limited to owner/authorized organizer.

## 3. Execution isolation
The Docker judge uses network-disabled containers, non-root execution, read-only filesystem, CPU/memory/process limits, dropped capabilities, no-new-privileges, and bounded output. Trusted workers require Docker access to launch judge containers; submitted-code containers do not receive the Docker socket or host credentials.

## 4. Verification and performance evidence
**Automated tests:** final recorded run: 15 passed, 1 dependency deprecation warning. Coverage includes worker concurrency/recovery, leaderboard, submission idempotency, and authentication/security.

**Observed verdict checks:** AC, WA, CE, TLE, RE, OLE. A worker crash/restart scenario was exercised and the expired work was recovered and completed.

**Concurrency/idempotency:** concurrent same-key requests returned the same submission ID; different keys created separate IDs. Worker tests coordinate claims and assert persistent state, including duplicate claim prevention, stale-worker fencing, lease recovery, and retry exhaustion.

**Load test:** Locust 2.43.1, 20 users, ramp-up 5/sec, 60 sec; 804 requests, 0 failures, 13.48 req/sec, average 11 ms, median 7 ms, P95 16 ms, max 219 ms. Workload covered authentication and contest/problem/leaderboard reads; results are environment-specific.

**Database:** 27 indexes inspected. Organization-contest query used `ix_contests_org_start` Index Scan (0.049 ms). Submission and queued-attempt queries used Seq Scan on small tables (0.030 ms and 0.015 ms); further index tuning should be based on larger data.

## 5. Investigated failure: worker interruption and recovery
A submission was left in the running state while worker 1 was stopped. The attempt's lease expired. After worker restart, recovery logic detected the expired work, requeued/reclaimed it, and it subsequently completed with the observed TLE verdict. This exercised restart recovery rather than relying on sleep-only timing. The result was checked through the persisted submission status. Retry exhaustion is also covered by a concurrency test.

## 6. Reproducibility metadata
Commit: `3805aa4` (assessment commit recorded in Git).
Configuration: Docker Compose local services; PostgreSQL database; API and two worker services; Docker judge execution.
Load-test mode: Locust headless, 20 users, 5 users/sec ramp, 60 seconds.
Dataset: demo identities seeded by `seeds/seed_auth.py` (2 organizations, 4 accounts: 1 organizer and 1 participant per organization). The recorded E2E contest/problem/test-suite IDs are in the development notes; this run's load workload targeted the seeded Org One contest. Dataset was a small development dataset, not a production-scale fixture.
Execution mode: local Docker Compose, API/worker containers, shared PostgreSQL, Docker-in-Docker-host-socket style runner access (trusted workers launch isolated judge containers).

## 7. Limitations
Rejudge workflow is not implemented. Load test is short/read-heavy and does not establish production capacity. Larger generated datasets, write/submission workloads, broader authorization tests, health checks/metrics/alerting, deployment hardening, and further worker/outbox edge-case review remain.

## 8. Conclusion
Core contest lifecycle, asynchronous judging, idempotency, version pinning, organization access checks, concurrency/recovery, and bounded Docker execution were implemented and verified with recorded local evidence. Limitations are explicitly identified.
