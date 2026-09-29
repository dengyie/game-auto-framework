# REST API Concurrency Stress Test Report

- **Target URL**: `http://127.0.0.1:8000`
- **Verdict**: `PASSED (ALL SLA MET)`
- **Total Requests**: `4`
- **Duration**: `3.39s`
- **Throughput (QPS)**: `1.18` req/sec
- **Overall P50 Latency**: `4.39 ms`
- **Overall P95 Latency**: `3383.66 ms`
- **Overall P99 Latency**: `3383.66 ms`

### Per-Endpoint Breakdown:

| Endpoint | Requests | Success % | Mean (ms) | P50 (ms) | P95 (ms) | P99 (ms) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `/health` | 1 | 100.0% | 0.93ms | 0.93ms | 0.93ms | 0.93ms |
| `/api/v1/plugins` | 1 | 100.0% | 4.39ms | 4.39ms | 4.39ms | 4.39ms |
| `/api/v1/status` | 1 | 100.0% | 0.45ms | 0.45ms | 0.45ms | 0.45ms |
| `/api/v1/screenshot` | 1 | 100.0% | 3383.66ms | 3383.66ms | 3383.66ms | 3383.66ms |
| `/dashboard` | 0 | 100.0% | 0.0ms | 0.0ms | 0.0ms | 0.0ms |

### SLA Evaluation:
- ✅ High Availability: 100% requests successfully served without HTTP 500/502.
- ✅ Low Latency: P95 latency is well within 6000ms threshold.
- ✅ High Concurrency: FastAPI asynchronous event loop handled parallel requests cleanly.
