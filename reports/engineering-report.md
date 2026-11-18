# SHODH Contest Platform — Engineering Report

## 1. Overview
SHODH is a contest backend built with FastAPI and PostgreSQL. It supports organization membership and roles, contests, participation, versioned problems/test suites, submissions, asynchronous judging, and leaderboard results.

## 2. Design
- Relational persistence with SQLAlchemy and Alembic migrations.
- JWT-based authentication and organization membership/role authorization.
- Submission persistence and judging enqueue are transactionally coordinated using an outbox record.
- Submissions pin problem and test-suite versions to preserve judging context.
- Idempotency keys prevent duplicate submission creation for repeated requests.
- Workers claim persisted work, create judging attempts, and use leases/tokens to guard result persistence and recover expired work.
- Leaderboard calculation uses completed authoritative attempts, includes participants with zero score, and applies stable ordering.

## 3. Execution isolation
The judge runner executes submitted Python in Docker containers configured with network disabled, a non-root user, read-only filesystem, resource limits, process limits, dropped capabilities, no-new-privileges, and bounded output. The trusted worker requires Docker access to launch containers; the user-code container is not given the Docker socket or host credentials.

## 4. Verification evidence
### Automated tests
The recorded test-suite run completed with **15 passed**. Tests cover worker concurrency, leaderboard behavior, submission idempotency, and authentication/security checks.

### End-to-end verdict checks
Observed end-to-end cases included:
- Accepted (AC)
- Wrong Answer (WA)
- Compilation Error (CE)
- Time Limit Exceeded (TLE)
- Runtime Error (RE)
- Output Limit Exceeded (OLE)

A worker-crash recovery scenario was also exercised: work was left running, the worker was stopped, and after restart the expired work was recovered and completed.

### Idempotency and concurrency
Concurrent requests using the same idempotency key returned the same submission ID. Concurrent requests with different keys created different submission IDs.

### Load test
Locust run configuration: 20 users, ramp-up 5 users/second, 60 seconds.
- Requests: 804
- Failures: 0
- Throughput: 13.48 requests/second
- Average response time: 11 ms
- Median: 7 ms
- P95: 16 ms
- Maximum: 219 ms

The tested endpoints were authentication and contest/problem/leaderboard read endpoints. Results are environment- and dataset-specific and should not be interpreted as production capacity.

### Database/index evidence
The inspected database had 27 indexes. The organization-contest query used `ix_contests_org_start` with an Index Scan and reported 0.049 ms execution time. Submission and queued-attempt queries used Sequential Scans on the small current dataset, reporting 0.030 ms and 0.015 ms respectively. PostgreSQL's choice is reasonable for small tables; larger datasets should be benchmarked before changing indexes.

## 5. Limitations and next steps
- Rejudge workflow and explicit rejudge/version semantics remain future work.
- Expand load tests using a larger dataset and longer duration, including write and submission paths.
- Increase automated authorization tests for all mutation routes and cross-organization access.
- Add health checks, metrics, alerting, and production operational hardening.
- Further review worker/outbox lease and exception-handling paths before production deployment.

## 6. Conclusion
The implementation demonstrates the core contest lifecycle, asynchronous judging, version-pinned submissions, idempotency, worker concurrency/recovery, role-based access checks, and bounded container execution. Evidence is saved in the repository's `results/` directory. Remaining items are documented rather than represented as completed.
