<!-- markdownlint-disable-file MD033 MD045 -->
<div align="center">

# GameAutoFramework

**工业级通用游戏自动化与资源调度中台引擎，声明式 DAG 流水线、拟人仿生防封动力学与分布式集群调度**

[![License](https://img.shields.io/badge/license-MIT-green.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB.svg?style=flat-square&logo=python&logoColor=white)](https://python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-009688.svg?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![OpenCV](https://img.shields.io/badge/OpenCV-Headless-5C3EE8.svg?style=flat-square&logo=opencv&logoColor=white)](https://opencv.org/)
[![RapidOCR](https://img.shields.io/badge/RapidOCR-ONNX-blue.svg?style=flat-square)](https://github.com/RapidAI/RapidOCR)
[![Tests](https://img.shields.io/badge/tests-288%20passed-brightgreen.svg?style=flat-square)]()

[English](./README.md) · [简体中文](./README.zh-CN.md) · [设计哲学](#核心设计哲学) · [架构拓扑](#架构拓扑全景) · [核心特性](#核心能力矩阵) · [仿生防封](#拟人仿生动力学防封体系) · [快速上手](#快速开始) · [接口规范](#fastapi-控制面与微服务接口)

<br>

<p align="center">
  <b>彻底终结复杂手游与端游自动化中的坐标硬编码、断连假死死锁与高频机械封号风险。</b><br>
  采用工业级通用核心底座与游戏业务扩展插件彻底解耦架构，构建本地确定性零 Token 流水线与储备多模态视觉模型双层防御体系。<br>
  提供小于 3ms 的局部 dHash 差异哈希运动感知、三阶贝塞尔人体工学拟人防封轨迹、3800+ 离线 SQLite 题库模糊答题与三级递进自愈逃生看门狗。
</p>

</div>

---

## 核心设计哲学

### 1. 引擎底座与游戏业务彻底解耦
Core 核心引擎底座专注于高精度视觉感知、零拷贝硬件屏幕捕获、三阶贝塞尔曲线仿生驱动与增强型 DAG 流水线调度；上层游戏通过独立的 Plugin 业务扩展包（切图资源、标定坐标、Pipeline JSON 流水线）实现热插拔接入与动态生命周期挂载。

### 2. 双层防御与零 Token 架构 (Two-Tier Principle)
- **第一层：本地确定性流水线 (Zero-Token Local Pipeline)**：重复日常活动（师门、宝图、挖宝、运镖、秘境降妖、科举三界答题、门派日常等）绝对零 Token 外部依赖，100% 运行在本地轻量 DAG 状态机、RapidOCR ONNX 模型、OpenCV 模板多尺度金字塔与离线 SQLite 题库上。单步决策响应 30~300ms，达成 0 外部 API 成本。
- **第二层：储备多模态模型防御层 (Reserved VLM Tier)**：多模态视觉语言模型严格保留在极低频特殊场景——节日新玩法自主探索、未收录的新型防挂机旋转/文字点选复杂验证码破解，以及本地题库未覆盖的长尾冷门问答。

### 3. 现代化工业级技术借鉴
- **MaaFramework & Maa_MHXY_MG**：声明式 DAG 状态机流水线（动态节点跳转、失败自愈重试、全局高优先级中断拦截器），战斗状态解耦与多任务自动流转。
- **haungwanjun/mhxy_fz**：局部 dHash 汉明距离差分事件驱动，任务追踪栏优先寻路机制（直接点击右侧追踪栏驱动原生寻路，摒弃低效的大地图点击与 NPC 寻路）。
- **0xn0ne/MHXYExamAssistant**：本地 20,000+ 条 SQLite 题库与 RapidFuzz 模糊匹配，离线 15ms 零 Token 秒级作答。
- **wuliangyue/mhxy-escort & BestBurning/mhxy**：防挂机验证弹窗三级自愈防御与底层内核级驱动级仿真。
- **BetterGI**：DirectX/WGC 零拷贝硬件抓屏、透明穿透 Overlay HUD 交互与 ONNX 目标检测。
- **March7thAssistant**：现代 `uv` 极速工程体系、云游戏微端推流与 Docker 无头化 (Headless) 运行、全渠道异常告警。
- **Alas**：Cron+Priority 工业级优先级调度器、集群工作池看门狗守护与三级自愈逃生链 (Escape Sequence)。

---

## 架构拓扑全景

```text
game-auto-framework/
├── core/                  # 通用核心引擎底座
│   ├── capture/           # 屏幕捕获 (WGC/DXGI 零拷贝, minicap, ADB 截图缓存, Socket 流)
│   ├── cv/                # 视觉感知 (多尺度模板匹配 0.85~1.15x, NMS, dHash 汉明帧差分, 战斗检测)
│   ├── ocr/               # 文本提取 (RapidOCR ONNX + RapidFuzz 词元模糊纠错与屏幕定位)
│   ├── input/             # 拟人仿生驱动 (三阶贝塞尔曲线, 2D 高斯偏置点击, Dwell Time, 指腹微漂移)
│   └── device/            # 跨平台设备抽象与工厂 (Linux ADB / Win / Mac / Virtual)
├── scheduler/             # 调度与状态机
│   ├── dag.py             # 增强型 DAG Pipeline 引擎 (条件分支跳转, 上下文流, 中断拦截)
│   ├── escape.py          # 三级看门狗自愈逃生机制 (45s/120s/300s 递进脱困)
│   └── routine.py         # 日常任务链编排器与防挂机熔断保护
├── cluster/               # 分布式集群调度与节点守护
│   ├── node.py            # 多设备工作节点注册与生命周期管理
│   └── watchdog.py        # 边缘触发断连告警、低频探针自愈与自动重连
├── plugins/               # 游戏业务扩展包
│   └── mhxy_mobile/       # 业务插件：《梦幻西游手游》
│       ├── manifest.json  # 插件清单与元数据
│       ├── config/        # 1280x720 基准分辨率坐标与热区
│       ├── pipelines/     # 师门20轮、打图挖宝、运镖、防挂机拦截 JSON
│       └── custom/        # 本地智能题库答题 (QuizSolver) 与业务算子
├── server/                # FastAPI 远程调用微服务中枢 (单任务/任务链/截图流)
└── tests/                 # 35 个全量测试套件 (288 项测试全量通过)
```

---

## 核心能力矩阵

| 模块 | 能力项 | 技术细节与工程优势 |
| :--- | :--- | :--- |
| **四级级联视觉感知** | 多尺度模板与 dHash 差分 | 局部 dHash 差异哈希与汉明距离 (&lt;3ms) 过滤静止画面，画面无变化时休眠降低 70% CPU；OpenCV 多尺度金字塔与 NMS 非极大值抑制定位目标。 |
| **OCR 与模糊文本定位**| RapidOCR ONNX + RapidFuzz | 轻量 ONNX 模型完成毫秒级文字识别，配合 RapidFuzz 词元模糊纠错与反向屏幕中心标定，对字体抗锯齿及阴影具备极高鲁棒性。 |
| **拟人化仿生动力学** | 三阶贝塞尔与高斯微漂移 | 2D 高斯正态分布随机点击偏置；55~120ms 真实人体按压驻留时间；1~2px 指腹接触微漂移；启动加速、巡航与终点减速仿真轨迹。 |
| **增强型 DAG 流水线** | 声明式状态机与中断拦截 | 支持动态条件分支跳转 (`branches: [{"condition": "...", "next": "..."}]`)；上下文坐标跨节点透传；全局高优先级中断机制秒级拦截化解防挂机弹窗。 |
| **三级递进自愈逃生** | 递进脱困看门狗机制 | 45s (ESC 后退) -> 120s (长安回城/脱困传送) -> 300s (进程级硬重启拉起)，彻底解决寻路卡死与死锁卡滞。 |
| **本地离线智能题库** | 3854 条去重题库毫秒答 | 归一化去重合并 3854 条 SQLite 题库，RapidFuzz 0.82 阈值模糊匹配，0~3ms 零 Token 作答科举与三界奇缘，未命中启用 VLM 储备兜底。 |
| **多门派解耦战斗体系**| 门派策略注册表全覆盖 | 抽象 `SectCombatRegistry`，原生支持月宫、魔王寨、方寸山、普陀山等全主流门派；自动 OCR 技能词条识别并绑定；攻法血宠精细分发。 |
| **集群分布式看门狗** | 边缘触发自愈与探针巡检 | 多节点工作池监控、连续失败防雪崩重试计数、异常断开即时告警与手动重连 API。 |

---

## 拟人仿生动力学防封体系

平台风控体系通常通过点击坐标方差、按压时长分布、滑动速度曲率与空操作频率分析行为特征。本项目构建了全方位的底层拟人化驱动：

```text
┌────────────────────────────────────────────────────────────────────────┐
│                      拟人仿生驱动层 (core/input/)                      │
├────────────────────────────────────────────────────────────────────────┤
│ 1. 坐标高斯偏置: (x + N(0, σ_x), y + N(0, σ_y)) 杜绝像素几何中心连击   │
│ 2. 按压驻留时间: 55ms ~ 120ms 随机正态分布 Dwell Time 仿真指腹接触     │
│ 3. 接触微漂移:   按压期间模拟 1~2px 微小物理抖动 (Micro-Drift)         │
│ 4. 三阶贝塞尔:   P(t) = (1-t)³P₀ + 3(1-t)²tP₁ + 3(1-t)t²P₂ + t³P₃      │
│                  - 启动加速阶段 (Ease-In)                              │
│                  - 中途高速巡航 (Cruising Phase)                       │
│                  - 终点减速对准 (Ease-Out) 叠加正弦微扰抖动            │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 业务落地：《梦幻西游手游》(mhxy_mobile)

- **日常师门 (`daily_shimen`)**：20 轮自动计数闭环，涵盖师门接取、寻路、买药买物、道具上交与门派巡逻战斗。
- **宝图与连续挖宝 (`daily_baotu`)**：店小二接取、贼王追踪战斗、10 轮计数与自动开包连续 10 张挖宝结算闭环。
- **天下运镖 (`daily_yuntong`)**：50 活跃度门槛动态提取与延迟补跑机制；郑镖头领镖、巡航走图、遇敌战斗与送达结算闭环。
- **秘境降妖 (`daily_mijing`)**：实机校准闯关进度（+25 活跃度动态累计），主城 HUD 一票否决防答题误判，含仙玉弹窗严密安全退出保护。
- **科举与三界奇缘 (`quiz`)**：3854 条 SQLite 题库 + RapidFuzz 模糊匹配，毫秒级零 Token 秒答。
- **多门派战斗矩阵 (`combat_strategy.py`)**：月宫群单秒切换、魔王寨法术点杀、方寸山封印控制、普陀山治疗复活与首回合精确施法后自动挂机保护。

---

## 快速开始

### 1. 安装环境与依赖

本项目采用现代化 `uv` 进行依赖管理与环境同步，推荐 Python 3.12+：

```bash
# 克隆代码仓库
git clone https://github.com/dengyie/game-auto-framework.git
cd game-auto-framework

# 使用 uv 一键同步虚拟环境与依赖
uv sync

# 或者使用 pip 在已激活的虚拟环境中安装
pip install -e .
```

### 2. 运行自动化测试套件

执行全量单元与集成测试（涵盖 DAG 状态机、视觉引擎、题库匹配、集群调度等）：

```bash
uv run pytest tests/
```

### 3. 启动 FastAPI 调度中枢

```bash
uv run uvicorn server.app:app --host 0.0.0.0 --port 8000
```

访问 `http://127.0.0.1:8000/docs` 查看交互式 OpenAPI (Swagger) 接口控制台。

---

## FastAPI 控制面与微服务接口

| 路径 | 方法 | 功能说明 |
| :--- | :--- | :--- |
| `/api/v1/tasks/start-routine` | `POST` | 启动日常任务流水线（如 `["shimen", "baotu", "yuntong"]`） |
| `/api/v1/tasks/routine-status` | `GET` | 查询当前任务链执行进度、当前步骤与状态 |
| `/api/v1/tasks/stop` | `POST` | 紧急制动并中断当前运行中的任务流水线 |
| `/api/v1/cluster/nodes` | `GET` | 查询分布式集群内受管控设备节点与在线状态 |
| `/api/v1/cluster/reconnect` | `POST` | 手动触发指定节点 ADB/Socket 重新连接 |
| `/api/v1/device/screenshot` | `GET` | 获取指定设备当前屏幕实时帧图像流 |

---

## 质量保证与自动化测试

本项目坚持严格的证据驱动与测试覆盖，全量套件基于 `pytest` 构建：

- **测试用例规模**：全量 **299** 项测试用例，涵盖 35 个专项测试模块；
- **执行结果**：**288 passed**，11 skipped（真实真机硬件 ADB 与实机游戏验收测试需外接设备，其余本地回归全绿）；
- **覆盖领域**：
  - `test_cv_engine`: 多尺度模板匹配、NMS 抑制、dHash 汉明帧差与脱战检测；
  - `test_bezier`: 三阶贝塞尔速度曲线、插值平滑度与正弦微扰收敛性；
  - `test_dag` & `test_dag_stall_watchdog`: 动态分支路由、上下文跨节点透传与卡滞超时中断；
  - `test_daily_guards`: 屏幕边缘防越界点击、活动面板尺寸自适应与防连续误触降级；
  - `test_quiz_solver`: 题干清洗正则、SQLite 索引命中与 RapidFuzz 模糊匹配评分；
  - `test_cluster`: 节点心跳追踪、连续失败自愈、边缘告警与看门狗状态机。

---

## 参与贡献与许可证

欢迎提交 Issue 与 Pull Request！在提交代码变更前，请确保全量测试套件执行通过：

```bash
uv run pytest tests/
```

本项目采用 [MIT License](LICENSE) 开源协议。
