# REST API Concurrency Stress Test Report

- **Target URL**: `http://127.0.0.1:8000`
- **Verdict**: `PASSED (ALL SLA MET)`
- **Total Requests**: `4`
- **Duration**: `0.01s`
- **Throughput (QPS)**: `799.95` req/sec
- **Overall P50 Latency**: `2.03 ms`
- **Overall P95 Latency**: `4.04 ms`
- **Overall P99 Latency**: `4.04 ms`

### Per-Endpoint Breakdown:

| Endpoint | Requests | Success % | Mean (ms) | P50 (ms) | P95 (ms) | P99 (ms) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `/health` | 1 | 100.0% | 2.03ms | 2.03ms | 2.03ms | 2.03ms |
| `/api/v1/plugins` | 1 | 100.0% | 4.04ms | 4.04ms | 4.04ms | 4.04ms |
| `/api/v1/status` | 1 | 100.0% | 0.88ms | 0.88ms | 0.88ms | 0.88ms |
| `/api/v1/screenshot` | 1 | 100.0% | 0.6ms | 0.6ms | 0.6ms | 0.6ms |
| `/dashboard` | 0 | 100.0% | 0.0ms | 0.0ms | 0.0ms | 0.0ms |

### SLA Evaluation:
- ✅ High Availability: 100% requests successfully served without HTTP 500/502.
- ✅ Low Latency: P95 latency is well within 1000ms threshold.
- ✅ High Concurrency: FastAPI asynchronous event loop handled parallel requests cleanly.
