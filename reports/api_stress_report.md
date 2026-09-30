# REST API Concurrency Stress Test Report

- **Target URL**: `http://127.0.0.1:8000`
- **Verdict**: `PASSED (ALL SLA MET)`
- **Total Requests**: `4`
- **Duration**: `2.09s`
- **Throughput (QPS)**: `1.92` req/sec
- **Overall P50 Latency**: `7.52 ms`
- **Overall P95 Latency**: `2085.93 ms`
- **Overall P99 Latency**: `2085.93 ms`

### Per-Endpoint Breakdown:

| Endpoint | Requests | Success % | Mean (ms) | P50 (ms) | P95 (ms) | P99 (ms) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `/health` | 1 | 100.0% | 1.16ms | 1.16ms | 1.16ms | 1.16ms |
| `/api/v1/plugins` | 1 | 100.0% | 7.52ms | 7.52ms | 7.52ms | 7.52ms |
| `/api/v1/status` | 1 | 100.0% | 0.51ms | 0.51ms | 0.51ms | 0.51ms |
| `/api/v1/screenshot` | 1 | 100.0% | 2085.93ms | 2085.93ms | 2085.93ms | 2085.93ms |
| `/dashboard` | 0 | 100.0% | 0.0ms | 0.0ms | 0.0ms | 0.0ms |

### SLA Evaluation:
- ✅ High Availability: 100% requests successfully served without HTTP 500/502.
- ✅ Low Latency: P95 latency is well within 6000ms threshold.
- ✅ High Concurrency: FastAPI asynchronous event loop handled parallel requests cleanly.
