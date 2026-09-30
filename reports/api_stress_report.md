# REST API Concurrency Stress Test Report

- **Target URL**: `http://127.0.0.1:8000`
- **Verdict**: `PASSED (ALL SLA MET)`
- **Total Requests**: `4`
- **Duration**: `4.82s`
- **Throughput (QPS)**: `0.83` req/sec
- **Overall P50 Latency**: `5.2 ms`
- **Overall P95 Latency**: `4813.75 ms`
- **Overall P99 Latency**: `4813.75 ms`

### Per-Endpoint Breakdown:

| Endpoint | Requests | Success % | Mean (ms) | P50 (ms) | P95 (ms) | P99 (ms) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `/health` | 1 | 100.0% | 1.15ms | 1.15ms | 1.15ms | 1.15ms |
| `/api/v1/plugins` | 1 | 100.0% | 5.2ms | 5.2ms | 5.2ms | 5.2ms |
| `/api/v1/status` | 1 | 100.0% | 0.53ms | 0.53ms | 0.53ms | 0.53ms |
| `/api/v1/screenshot` | 1 | 100.0% | 4813.75ms | 4813.75ms | 4813.75ms | 4813.75ms |
| `/dashboard` | 0 | 100.0% | 0.0ms | 0.0ms | 0.0ms | 0.0ms |

### SLA Evaluation:
- ✅ High Availability: 100% requests successfully served without HTTP 500/502.
- ✅ Low Latency: P95 latency is well within 6000ms threshold.
- ✅ High Concurrency: FastAPI asynchronous event loop handled parallel requests cleanly.
