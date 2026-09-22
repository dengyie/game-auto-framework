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
│   ├── cv/                # 视觉感知 (OpenCV 模板匹配, 局部汉明距离)
│   ├── ocr/               # 文本提取 (RapidOCR + RapidFuzz 模糊比对)
│   └── input/             # 拟人化驱动 (三阶贝塞尔曲线, 二维高斯随机偏置, 内核驱动)
├── scheduler/             # 调度与状态机
│   ├── dag.py             # 声明式 DAG Pipeline 引擎
│   ├── escape.py          # 三级自愈脱困逃生机制
│   └── cron.py            # Cron + Priority 任务调度器
├── plugins/               # 游戏业务扩展包
│   └── mhxy_mobile/       # 首发插件：《梦幻西游手游》
│       ├── manifest.json  # 插件清单
│       ├── config/        # 基准分辨率参考坐标
│       ├── pipelines/     # 师门、抓鬼、挖宝、防挂机拦截 JSON
│       └── custom/        # 自定义 AI 答题与特殊业务算子
├── server/                # Web API 与 MCP Server 桥接
└── tests/                 # 单元测试与端到端测试
```

## 快速开始

```bash
# 使用 uv 同步依赖
uv sync

# 运行核心算子测试
uv run pytest tests/
```
