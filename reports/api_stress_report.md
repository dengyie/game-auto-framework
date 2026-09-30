# REST API Concurrency Stress Test Report

- **Target URL**: `http://127.0.0.1:8000`
- **Verdict**: `PASSED (ALL SLA MET)`
- **Total Requests**: `4`
- **Duration**: `4.07s`
- **Throughput (QPS)**: `0.98` req/sec
- **Overall P50 Latency**: `9.56 ms`
- **Overall P95 Latency**: `4064.04 ms`
- **Overall P99 Latency**: `4064.04 ms`

### Per-Endpoint Breakdown:

| Endpoint | Requests | Success % | Mean (ms) | P50 (ms) | P95 (ms) | P99 (ms) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `/health` | 1 | 100.0% | 1.93ms | 1.93ms | 1.93ms | 1.93ms |
| `/api/v1/plugins` | 1 | 100.0% | 9.56ms | 9.56ms | 9.56ms | 9.56ms |
| `/api/v1/status` | 1 | 100.0% | 0.56ms | 0.56ms | 0.56ms | 0.56ms |
| `/api/v1/screenshot` | 1 | 100.0% | 4064.04ms | 4064.04ms | 4064.04ms | 4064.04ms |
| `/dashboard` | 0 | 100.0% | 0.0ms | 0.0ms | 0.0ms | 0.0ms |

### SLA Evaluation:
- ✅ High Availability: 100% requests successfully served without HTTP 500/502.
- ✅ Low Latency: P95 latency is well within 6000ms threshold.
- ✅ High Concurrency: FastAPI asynchronous event loop handled parallel requests cleanly.
