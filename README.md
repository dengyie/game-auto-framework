<!-- markdownlint-disable-file MD033 MD045 -->
<div align="center">

# GameAutoFramework

**Industrial General-Purpose Game Automation & Farming Engine with Declarative DAG Pipelines, Biometric Anti-Detection Dynamics, and Distributed Cluster Scheduling**

[![License](https://img.shields.io/badge/license-MIT-green.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB.svg?style=flat-square&logo=python&logoColor=white)](https://python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-009688.svg?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![OpenCV](https://img.shields.io/badge/OpenCV-Headless-5C3EE8.svg?style=flat-square&logo=opencv&logoColor=white)](https://opencv.org/)
[![RapidOCR](https://img.shields.io/badge/RapidOCR-ONNX-blue.svg?style=flat-square)](https://github.com/RapidAI/RapidOCR)
[![Tests](https://img.shields.io/badge/tests-288%20passed-brightgreen.svg?style=flat-square)]()

[English](./README.md) · [简体中文](./README.zh-CN.md) · [Philosophy](#core-design-philosophy) · [Architecture](#system-architecture--topology) · [Core Features](#core-feature-matrix) · [Biometrics](#biometric-dynamics--anti-detection) · [Quick Start](#quick-start) · [API Specs](#fastapi-control-plane--microservice-apis)

<br>

<p align="center">
  <b>Terminates repetitive manual grinding, rigid coordinate hardcoding, and catastrophic ban risks across complex mobile and desktop gaming titles.</b><br>
  Engineered with a clean separation between an industrial core engine and hot-swappable business plugins, combining deterministic zero-token local DAG pipelines with reserved VLM multimodal escalation.<br>
  Provides dHash sub-3ms motion filtering, cubic Bezier biometric trajectory smoothing with Gaussian jitter, 3800+ offline RapidFuzz quiz solving, and multi-tier progressive escape watchdogs.
</p>

</div>

---

## Core Design Philosophy

### 1. Engine Core & Game Business Decoupling
The Core engine base focuses strictly on high-precision computer vision perception, zero-copy hardware screen capture, cubic Bezier curve bionic input synthesis, and an enhanced DAG pipeline scheduler. Target games integrate via isolated, hot-swappable business plugins (`plugins/`) containing image assets, calibration templates, and declarative JSON workflow graphs.

### 2. Two-Tier Defense & Zero-Token Architecture
- **Tier 1: Deterministic Zero-Token Local Pipeline**: High-frequency daily farming routines (sect tasks, treasure maps, escorts, secret realms, trivia quizzes) run with absolute zero external token dependencies. Workflows execute locally via lightweight DAG state machines, RapidOCR ONNX inference, OpenCV multi-scale template pyramids, and local SQLite question banks. Step latency spans 30-300ms at exactly $0 external API cost.
- **Tier 2: Reserved Multimodal VLM Escalation**: Vision-language models (VLMs) remain reserved strictly for rare anomaly resolution: autonomous exploration of unmapped holiday events, solving novel anti-bot rotation or click-choice captchas, and long-tail questions unindexed in local databases.

### 3. Open-Source Architectural Inspirations
- **MaaFramework & Maa_MHXY_MG (Maa Ecosystem)**: Declarative DAG state machines, condition branching, recovery retries, and high-priority global interruption interceptors.
- **haungwanjun/mhxy_fz**: Localized dHash Hamming distance difference event loops and quest-tracker priority pathfinding (driving native navigation directly through quest tracker HUD targets).
- **0xn0ne/MHXYExamAssistant**: Offline SQLite knowledge base with RapidFuzz token matching for 15ms zero-token trivia answers.
- **wuliangyue/mhxy-escort & BestBurning/mhxy**: Anti-bot popup multi-tier defense and driver-level input emulation.
- **BetterGI**: DirectX/WGC zero-copy hardware screen capture, transparent overlay HUD interaction, and ONNX object detection.
- **March7thAssistant**: Modern `uv` packaging, cloud streaming container headless execution, and multi-channel incident notification.
- **Alas**: Priority-based industrial scheduling, worker pool watchdogs, and progressive 3-tier escape sequences.

---

## System Architecture & Topology

```text
game-auto-framework/
├── core/                  # General-purpose core engine base
│   ├── capture/           # Screen capture (WGC/DXGI zero-copy, minicap, ADB cache, socket stream)
│   ├── cv/                # Vision perception (Multi-scale template 0.85-1.15x, NMS, dHash Hamming delta)
│   ├── ocr/               # Text extraction (RapidOCR ONNX + RapidFuzz token fuzzy correction)
│   ├── input/             # Biometric input driver (Cubic Bezier, 2D Gaussian offset, Dwell time, micro-drift)
│   └── device/            # Cross-platform device abstractions (Linux ADB / Win / Mac / Virtual)
├── scheduler/             # Scheduling & state machine
│   ├── dag.py             # Enhanced DAG pipeline engine (dynamic branching, context flow, interrupt handling)
│   ├── escape.py          # 3-tier watchdog progressive escape mechanism (45s/120s/300s)
│   └── routine.py         # Daily routine task orchestrator & circuit breaker
├── cluster/               # Distributed cluster orchestration & node watchdog
│   ├── node.py            # Multi-device worker registration & lifecycle state
│   └── watchdog.py        # Edge-triggered disconnect alarms, low-frequency probe self-healing
├── plugins/               # Business expansion plugins
│   └── mhxy_mobile/       # Production plugin: Fantasy Westward Journey Mobile
│       ├── manifest.json  # Plugin metadata & dependencies
│       ├── config/        # 1280x720 reference resolution coordinates & hot zones
│       ├── pipelines/     # Sect 20-round, treasure digging, escort, anti-bot JSON graphs
│       └── custom/        # Offline trivia solver (QuizSolver) & custom operators
├── server/                # FastAPI microservice central controller
└── tests/                 # 35 test suites (288 tests passed, 11 skipped)
```

---

## Core Feature Matrix

| Capability | Module | Technical Implementation & Advantage |
| :--- | :--- | :--- |
| **Cascade Vision Perception** | `core/cv/` | Sub-3ms dHash Hamming distance motion filtering sleeps during static frames (reducing CPU usage by 70%); multi-scale template matching with NMS eliminates duplicate detections. |
| **High-Precision OCR** | `core/ocr/` | RapidOCR ONNX inference combined with RapidFuzz token scoring accurately locates button anchors across anti-aliased and shaded text fonts. |
| **Biometric Anti-Detection** | `core/input/` | 2D Gaussian random offset prevents centroid clustering; 55-120ms normal dwell times simulate real finger contact; 1-2px micro-drift during clicks; cubic Bezier curves with sinusoidal noise. |
| **Enhanced DAG Pipelines** | `scheduler/dag.py` | Declarative condition routing (`branches: [{"condition": "...", "next": "..."}]`), transient coordinate context propagation, and high-priority interrupt hooks for instant anti-bot mitigation. |
| **3-Tier Escape Watchdogs** | `scheduler/escape.py` | Progressive escalation: 45s (ESC backout) -> 120s (Return to Town / Escape scroll) -> 300s (Process hard restart) resolves stuck navigation and frozen states. |
| **Offline Trivia Engine** | `plugins/.../custom/` | Consolidated 3854-entry SQLite database with RapidFuzz 0.82 similarity threshold yields 0-3ms zero-token answers, with optional Tier-2 VLM fallback. |
| **Decoupled Combat Engine** | `SectCombatRegistry` | Unified sect combat registry supporting multiple classes (Moon Palace, Demon King, Fangcun, Putuo) with auto-OCR skill binding and pet target allocation. |
| **Cluster Node Management** | `cluster/` | Distributed worker pool heartbeat tracking, consecutive failure circuit breaking, edge-triggered disconnect alerts, and manual reconnect APIs. |

---

## Biometric Dynamics & Anti-Detection

Gaming risk-control algorithms track coordinate variance, click dwell duration distributions, swipe velocity curvature, and idle-time patterns. GameAutoFramework implements human-grade input synthesis:

```text
┌────────────────────────────────────────────────────────────────────────┐
│                   Biometric Input Layer (core/input/)                  │
├────────────────────────────────────────────────────────────────────────┤
│ 1. 2D Gaussian Offset: (x + N(0, σ_x), y + N(0, σ_y)) eliminates       │
│    repetitive centroid clicks on UI targets.                           │
│ 2. Human Dwell Time:   55ms - 120ms randomized normal distribution.    │
│ 3. Contact Micro-Drift: Simulates 1-2px finger tremor during press.    │
│ 4. Cubic Bezier Motion: P(t) = (1-t)³P₀ + 3(1-t)²tP₁ + 3(1-t)t²P₂ + t³P₃│
│    - Ease-In starting acceleration                                     │
│    - High-speed cruising phase                                         │
│    - Ease-Out terminal deceleration with sinusoidal micro-jitter       │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Production Plugin: Fantasy Westward Journey Mobile (`mhxy_mobile`)

- **Daily Sect Tasks (`daily_shimen`)**: Complete 20-round automated execution covering quest acquisition, navigation, shop purchases, item hand-ins, and patrol battles.
- **Treasure Maps & Digging (`daily_baotu`)**: NPC interaction, thief battles, 10-round tracking, and automatic sequential inventory digging.
- **Escort Service (`daily_yuntong`)**: Dynamic 50-activity threshold detection with delayed retry scheduling; escort route navigation and combat settlement.
- **Secret Realm (`daily_mijing`)**: Calibrated 25-activity milestone tracking; HUD check prevents trivia misinterpretation; jade popup security guard prevents unintended currency expenditure.
- **Trivia Quizzes (`quiz`)**: 3854-item SQLite question bank with RapidFuzz token matching for 0-3ms offline completion.
- **Combat Strategy Matrix (`combat_strategy.py`)**: Multi-target AOE vs single-target burst switching, pet spell dispatching, and turn-1 auto-battle activation to prevent idle detection.

---

## Quick Start

### 1. Environment & Dependencies

Modern `uv` package management is recommended (Python 3.12+):

```bash
# Clone the repository
git clone https://github.com/dengyie/game-auto-framework.git
cd game-auto-framework

# Sync dependencies with uv
uv sync

# Or install with pip in an active virtual environment
pip install -e .
```

### 2. Run Test Suite

Execute the comprehensive test suite locally:

```bash
uv run pytest tests/
```

### 3. Start FastAPI Server

```bash
uv run uvicorn server.app:app --host 0.0.0.0 --port 8000
```

Navigate to `http://127.0.0.1:8000/docs` to inspect the interactive Swagger API documentation.

---

## FastAPI Control Plane & Microservice APIs

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/v1/tasks/start-routine` | `POST` | Launches a multi-task routine sequence (e.g., `["shimen", "baotu", "yuntong"]`) |
| `/api/v1/tasks/routine-status` | `GET` | Retrieves current routine progression, step status, and error states |
| `/api/v1/tasks/stop` | `POST` | Dispatches an emergency brake signal to abort running pipelines |
| `/api/v1/cluster/nodes` | `GET` | Returns list of registered cluster device nodes and online statuses |
| `/api/v1/cluster/reconnect` | `POST` | Triggers a manual ADB/Socket reconnection for a specified node |
| `/api/v1/device/screenshot` | `GET` | Streams the real-time frame buffer of the specified device |

---

## Quality Assurance & Automated Testing

The repository maintains an evidence-based test suite driven by `pytest`:

- **Total Test Scale**: **299** test cases across 35 test suites;
- **Regression Outcome**: **288 passed**, 11 skipped (physical ADB device tests require hardware attachments; all local regressions 100% green);
- **Coverage Areas**:
  - `test_cv_engine`: Multi-scale matching, NMS suppression, dHash Hamming delta, and combat detection;
  - `test_bezier`: Cubic Bezier velocity curves, trajectory smoothness, and perturbation convergence;
  - `test_dag` & `test_dag_stall_watchdog`: Dynamic branch routing, context flow, and stall watchdog timeouts;
  - `test_daily_guards`: Frame-edge bounding, activity panel scaling, and repeated-click degradation;
  - `test_quiz_solver`: Prompt normalization, SQLite indexing, and RapidFuzz scoring;
  - `test_cluster`: Heartbeat tracking, consecutive failure self-healing, and watchdog state machines.

---

## Technology Stack

- **Runtime & Language**: Python 3.12+
- **Control Plane API**: FastAPI, Uvicorn, Starlette, HTTPX
- **Computer Vision**: OpenCV (Headless), NumPy, Pillow
- **OCR & Fuzzy Search**: RapidOCR (ONNX Runtime), RapidFuzz
- **Scheduling & Automation**: Declarative DAG Pipelines, Biometric Input Synthesis
- **Testing & QA**: Pytest, AnyIO

---

## Contributing & License

Issues and pull requests are welcome. Before submitting modifications, please verify that all tests pass:

```bash
uv run pytest tests/
```

This project is licensed under the [MIT License](LICENSE).
