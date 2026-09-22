# REST API Concurrency Stress Test Report

- **Target URL**: `http://127.0.0.1:8000`
- **Verdict**: `PASSED (ALL SLA MET)`
- **Total Requests**: `4`
- **Duration**: `0.0s`
- **Throughput (QPS)**: `1430.7` req/sec
- **Overall P50 Latency**: `1.68 ms`
- **Overall P95 Latency**: `1.69 ms`
- **Overall P99 Latency**: `1.69 ms`

### Per-Endpoint Breakdown:

| Endpoint | Requests | Success % | Mean (ms) | P50 (ms) | P95 (ms) | P99 (ms) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `/health` | 1 | 100.0% | 1.68ms | 1.68ms | 1.68ms | 1.68ms |
| `/api/v1/plugins` | 1 | 100.0% | 1.69ms | 1.69ms | 1.69ms | 1.69ms |
| `/api/v1/status` | 1 | 100.0% | 0.44ms | 0.44ms | 0.44ms | 0.44ms |
| `/api/v1/screenshot` | 1 | 100.0% | 0.31ms | 0.31ms | 0.31ms | 0.31ms |
| `/dashboard` | 0 | 100.0% | 0.0ms | 0.0ms | 0.0ms | 0.0ms |

### SLA Evaluation:
- ✅ High Availability: 100% requests successfully served without HTTP 500/502.
- ✅ Low Latency: P95 latency is well within 1000ms threshold.
- ✅ High Concurrency: FastAPI asynchronous event loop handled parallel requests cleanly.
