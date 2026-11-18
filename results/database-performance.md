# Database Performance Evidence

## Index Inventory
Total indexes: 27

Important indexes:
- ix_contests_org_start: contests (organization_id, starts_at)
- ix_submissions_contest_user: submissions (contest_id, user_id)
- ix_attempts_status: judging_attempts (status)
- ix_outbox_pending: outbox_events (published_at, created_at)
- uq_submission_idempotency: submissions (contest_id, user_id, idempotency_key)
- uq_contest_participant: participations (contest_id, user_id)
- uq_org_membership: organization_memberships (organization_id, user_id)

## EXPLAIN ANALYZE Results

### Contests by Organization
- Plan: Index Scan using ix_contests_org_start
- Execution time: 0.049 ms
- Index successfully used.

### Submissions by Contest and User
- Plan: Sequential Scan
- Rows examined: 20
- Execution time: 0.030 ms
- PostgreSQL selected sequential scan for the small dataset.

### Queued Judging Attempts
- Plan: Sequential Scan
- Rows examined: 20
- Execution time: 0.015 ms
- Sequential scan is reasonable for the current small dataset.

## Conclusion
The organization/start-time query uses its composite index successfully. PostgreSQL selected sequential scans for the submission and queued-attempt queries because the current tables are small. These plans should be reevaluated against a larger dataset before making further indexing changes.
