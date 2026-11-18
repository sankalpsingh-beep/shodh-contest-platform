# SHODH Load Test Results

## Configuration
- Tool: Locust 2.43.1
- Concurrent users: 20
- Ramp-up: 5 users/second
- Duration: 60 seconds
- Test date: 2026-11-18

## Overall Results
- Total requests: 804
- Failed requests: 0
- Failure rate: 0%
- Throughput: 13.48 requests/second
- Average response time: 11 ms
- Median response time: 7 ms
- 95th percentile: 16 ms
- Maximum response time: 219 ms

## Endpoint Results

| Endpoint | Requests | Average (ms) | P95 (ms) | Max (ms) |
|---|---:|---:|---:|---:|
| POST /auth/token | 20 | 169 | 220 | 220 |
| GET /contests/{id} | 187 | 5 | 9 | 25 |
| GET /contests/{id}/leaderboard | 199 | 9 | 15 | 39 |
| GET /contests/{id}/problems | 100 | 9 | 15 | 44 |
| GET /organizations/{id}/contests | 298 | 6 | 12 | 32 |

## Conclusion
The API completed this 60-second load test with 20 concurrent users and zero reported request failures. Read endpoints exhibited low response latency in this test environment. Authentication requests were slower than the read endpoints. These results represent this test configuration and do not establish maximum system capacity.
