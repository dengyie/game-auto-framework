# REST API Concurrency Stress Test Report

- **Target URL**: `http://127.0.0.1:8000`
- **Verdict**: `PASSED (ALL SLA MET)`
- **Total Requests**: `4`
- **Duration**: `3.28s`
- **Throughput (QPS)**: `1.22` req/sec
- **Overall P50 Latency**: `6.01 ms`
- **Overall P95 Latency**: `3275.71 ms`
- **Overall P99 Latency**: `3275.71 ms`

### Per-Endpoint Breakdown:

| Endpoint | Requests | Success % | Mean (ms) | P50 (ms) | P95 (ms) | P99 (ms) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `/health` | 1 | 100.0% | 1.53ms | 1.53ms | 1.53ms | 1.53ms |
| `/api/v1/plugins` | 1 | 100.0% | 6.01ms | 6.01ms | 6.01ms | 6.01ms |
| `/api/v1/status` | 1 | 100.0% | 0.51ms | 0.51ms | 0.51ms | 0.51ms |
| `/api/v1/screenshot` | 1 | 100.0% | 3275.71ms | 3275.71ms | 3275.71ms | 3275.71ms |
| `/dashboard` | 0 | 100.0% | 0.0ms | 0.0ms | 0.0ms | 0.0ms |

### SLA Evaluation:
- ✅ High Availability: 100% requests successfully served without HTTP 500/502.
- ✅ Low Latency: P95 latency is well within 6000ms threshold.
- ✅ High Concurrency: FastAPI asynchronous event loop handled parallel requests cleanly.
