# game-auto-framework

> 工业级通用游戏自动化与搬砖中台调度引擎 (General Game Automation & Farming Framework)

## 核心设计哲学
- **引擎与业务彻底解耦**：Core 引擎专注于高精度感知、低延迟屏幕抓取、三阶贝塞尔拟人化输入与 DAG 流水线调度；上层游戏通过独立的 Plugin 扩展包（切图、坐标、Pipeline JSON）热插拔接入。
- **现代化顶层技术体系借鉴**：
  - **BetterGI (15.6k⭐)**：DirectX/WGC 零拷贝硬件抓屏、透明穿透 Overlay HUD 交互、ONNX 目标检测。
  - **March7thAssistant (11.5k⭐)**：现代 `uv` 工程体系、云游戏微端推流与 Docker 无头化 (Headless) 运行、全渠道异常推送。
  - **MaaFramework (4.9k⭐ & MAA 23.4k⭐)**：声明式 DAG 状态机流水线（节点跳转、重试自愈、全局中断拦截器）。
  - **Alas (4.0k⭐)**：Cron+Priority 工业级调度器、集群池看门狗守护、三级自愈逃生链 (Escape Sequence)。

## 架构拓扑
```
game-auto-framework/
├── core/                  # 通用核心引擎底座
│   ├── capture/           # 屏幕捕获 (WGC/DXGI, minicap, ADB, Socket流)
│   ├── cv/                # 视觉感知 (多尺度模板匹配, NMS, dHash 汉明帧差分, 战斗检测)
│   ├── ocr/               # 文本提取 (RapidOCR ONNX + RapidFuzz 模糊纠错与屏幕定位)
│   ├── input/             # 拟人仿生驱动 (三阶贝塞尔曲线, 高斯偏置点击, Dwell Time, 指腹微漂移)
│   └── device/            # 跨平台设备抽象与工厂 (Linux ADB / Win / Mac / Virtual)
├── scheduler/             # 调度与状态机
│   ├── dag.py             # 增强型 DAG Pipeline 引擎 (动态分支, 上下文流, 中断拦截)
│   ├── escape.py          # 三级看门狗自愈逃生机制 (45s/120s/300s 递进脱困)
│   └── routine.py         # 日常任务链编排器与防挂机熔断保护
├── plugins/               # 游戏业务扩展包
│   └── mhxy_mobile/       # 首发插件：《梦幻西游手游》
│       ├── manifest.json  # 插件清单与元数据
│       ├── config/        # 1280x720 基准分辨率坐标与热区
│       ├── pipelines/     # 师门20轮、打图挖宝、运镖、防挂机拦截 JSON
│       └── custom/        # 本地智能题库答题 (QuizSolver) 与业务算子
├── server/                # FastAPI 远程调用微服务中枢 (单任务/任务链/截图流)
└── tests/                 # 9 大测试套件 (31 项测试 100% 通过)
```

## 核心能力矩阵 (Milestone 1)

1. **四级级联视觉感知体系**：
   - `dHash` 差异哈希与汉明距离 (<3ms) 过滤静止画面，画面静止时休眠降低 70% CPU。
   - OpenCV 归一化互相关匹配与多尺度金字塔 (0.85~1.15x)，结合 NMS 非极大值抑制。
   - 自动战斗 UI 区域匹配与金色高光 HSV 掩模毫秒级脱战状态研判。
   - RapidOCR ONNX 轻量中文模型与 RapidFuzz 局部/词元模糊纠错，反向定位屏幕中心。
2. **拟人化仿生动力学防封**：
   - 2D 高斯正态分布随机点击偏置，杜绝像素几何中心连点。
   - 真实人体按压驻留时间 (55~120ms Dwell Time) 配合 1~2px 指腹接触微漂移 (Micro-Drift)。
   - 三阶贝塞尔曲线模拟启动加速 (Ease-in)、巡航与终点减速 (Ease-out)，叠加正弦微抖动。
3. **增强型 DAG 状态机与看门狗自愈**：
   - 声明式节点动态条件分支 (`branches: [{"condition": "...", "next": "..."}]`)。
   - 上下文瞬态坐标自动捕获与跨节点传递 (`last_match_point` / `last_text_point`)。
   - 全局高优先级中断机制实时阻断防挂机验证弹窗。
   - 45s (ESC后退) / 120s (长安回城) / 300s (进程硬重启) 三级递进式自愈脱困。
4. **首发业务落地：《梦幻西游手游》(mhxy_mobile)**：
   - `daily_shimen`: 20 轮自动计数闭环（接取/寻路/买药/上交/巡逻战斗）。
   - `daily_baotu`: 店小二接取、贼王战斗、10 轮计数与自动开包连续 10 张挖宝闭环。
   - `daily_yuntong`: 郑镖头领镖、巡航走图、遇敌战斗、送达结算闭环。
   - `quiz`: 内置科举与三界奇缘题库，RapidFuzz 模糊匹配精准定位选项。
   - `anti_bot_interceptor`: 弹窗全天候毫秒级拦截化解。
5. **日常任务链与熔断保护**：
   - `TaskRoutineExecutor` 顺序串联执行 `["shimen", "baotu", "yuntong"]`。
   - 防挂机连续识别失败自动触发 `CIRCUIT_BROKEN` 安全制动，坚决防范账号进苦行。
   - FastAPI 服务端提供 `POST /api/v1/tasks/start-routine` 与 `GET /api/v1/tasks/routine-status`。

## 快速开始

```bash
# 1. 使用 uv 同步依赖
uv sync

# 2. 运行全链路自动化测试
uv run pytest tests/

# 3. 启动 FastAPI 远程中枢
uv run uvicorn server.app:app --host 0.0.0.0 --port 8000
```

