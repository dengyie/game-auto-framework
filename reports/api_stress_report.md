# REST API Concurrency Stress Test Report

- **Target URL**: `http://127.0.0.1:8000`
- **Verdict**: `FAILED`
- **Total Requests**: `4`
- **Duration**: `1.2s`
- **Throughput (QPS)**: `3.34` req/sec
- **Overall P50 Latency**: `7.75 ms`
- **Overall P95 Latency**: `1194.62 ms`
- **Overall P99 Latency**: `1194.62 ms`

### Per-Endpoint Breakdown:

| Endpoint | Requests | Success % | Mean (ms) | P50 (ms) | P95 (ms) | P99 (ms) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `/health` | 1 | 100.0% | 1.39ms | 1.39ms | 1.39ms | 1.39ms |
| `/api/v1/plugins` | 1 | 100.0% | 7.75ms | 7.75ms | 7.75ms | 7.75ms |
| `/api/v1/status` | 1 | 100.0% | 0.39ms | 0.39ms | 0.39ms | 0.39ms |
| `/api/v1/screenshot` | 1 | 100.0% | 1194.62ms | 1194.62ms | 1194.62ms | 1194.62ms |
| `/dashboard` | 0 | 100.0% | 0.0ms | 0.0ms | 0.0ms | 0.0ms |

### SLA Evaluation:
- ❌ P95 latency 1194.62ms > 1000ms SLA limit
