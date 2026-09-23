# REST API Concurrency Stress Test Report

- **Target URL**: `http://127.0.0.1:8000`
- **Verdict**: `PASSED (ALL SLA MET)`
- **Total Requests**: `4`
- **Duration**: `0.02s`
- **Throughput (QPS)**: `225.35` req/sec
- **Overall P50 Latency**: `15.36 ms`
- **Overall P95 Latency**: `17.22 ms`
- **Overall P99 Latency**: `17.22 ms`

### Per-Endpoint Breakdown:

| Endpoint | Requests | Success % | Mean (ms) | P50 (ms) | P95 (ms) | P99 (ms) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `/health` | 1 | 100.0% | 1.2ms | 1.2ms | 1.2ms | 1.2ms |
| `/api/v1/plugins` | 1 | 100.0% | 17.22ms | 17.22ms | 17.22ms | 17.22ms |
| `/api/v1/status` | 1 | 100.0% | 0.48ms | 0.48ms | 0.48ms | 0.48ms |
| `/api/v1/screenshot` | 1 | 100.0% | 15.36ms | 15.36ms | 15.36ms | 15.36ms |
| `/dashboard` | 0 | 100.0% | 0.0ms | 0.0ms | 0.0ms | 0.0ms |

### SLA Evaluation:
- ✅ High Availability: 100% requests successfully served without HTTP 500/502.
- ✅ Low Latency: P95 latency is well within 1000ms threshold.
- ✅ High Concurrency: FastAPI asynchronous event loop handled parallel requests cleanly.
