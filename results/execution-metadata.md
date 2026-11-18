# Execution and Results Metadata

- Git commit: `3805aa4`
- Test command: `docker compose exec -e PYTHONPATH=/app -e TEST_DATABASE_URL="postgresql+psycopg://shodh:shodh_dev_password@db:5432/shodh_test" api python -m pytest -v`
- Recorded functional result: 15 passed; 1 dependency deprecation warning
- Configuration: Docker Compose local; PostgreSQL; API; worker1 and worker2; trusted worker launches Docker judge containers
- Dataset/seed: `seeds/seed_auth.py`; 2 organizations, 4 demo identities (organizer + participant per organization). Small development dataset.
- Load execution mode: Locust headless, 20 concurrent users, 5 users/sec ramp, 60 sec, read-heavy contest/problem/leaderboard and login routes
- Load result: 804 requests, 0 failures, 13.48 req/sec, average 11 ms, median 7 ms, P95 16 ms, max 219 ms
- Load result files: `locust_stats.csv`, `locust_stats_history.csv`, `locust_failures.csv`, `locust_exceptions.csv`
- Failure investigation: worker interruption while work was running; lease expiry and restart recovery observed; recovered submission completed TLE. Concurrency test also covers lease recovery and retry exhaustion.
- Data version: seed script plus small persisted local test/E2E dataset; no separate immutable dataset release/version was created for the benchmark.
