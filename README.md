# dglab-esp32-sniffer

用 ESP32 模拟 DG-LAB 刺激器，让官方 App 连接后**抓取蓝牙控制指令**，并通过网页实时显示波形（带刻度、缩放、累积时间轴、SSE 实时推送）。

> ⚠️ **仅供个人学习、研究与调试使用，严禁商用。** 详见 [LICENSE](LICENSE)。
>
> 本项目与 DG-LAB 官方无隶属或授权关系。协议与商标版权归 DG-LAB（Dungeon Lab）及其 App 作者所有。

## 能做什么

- ESP32 伪装成 DG-LAB 设备（`47L121000`），官方 App 可连接
- 抓取 App 发出的真实控制指令：`B0`（刺激）、`BF`（软限制）、`BC`（波形）、`50`/`66`（配置）、`FF`（启动）等
- 网页实时示波器：A/B 双通道脉冲波形、强度/时间刻度、1×~8× 缩放、约 9 秒累积滚动时间轴
- 无信号时时间轴照常走（画平线），像监护仪一样
- SSE 服务器推送，零延迟，不漏帧（App 每 100ms 一帧也能跟上）

## 目录结构

```
dglab-esp32-sniffer/
├── LICENSE                         版权声明（禁止商用）
├── README.md                       本文档
├── firmware/
│   └── FakeCoyote/
│       └── FakeCoyote.ino          ESP32 固件（Arduino）
├── capture/
│   ├── capture_server.py           抓包 Web 服务器（含实时示波器页面）
│   └── capture_serial.py           纯串口抓包脚本（可选）
└── docs/
    └── PROTOCOL.md                 协议笔记（自制整理）
```

## 硬件

- ESP32 开发板（测试用 ESP32-D0WD-V3，经典款，带 BLE）
- USB 线连接电脑

## 快速开始

### 1. 环境

- Arduino IDE 或 Arduino CLI，安装 ESP32 开发板支持包（测试用 esp32:esp32 4.0.0）
- Python 3 + `pyserial`

```bash
pip install pyserial
```

### 2. 烧录固件

用 Arduino IDE 打开 `firmware/FakeCoyote/FakeCoyote.ino`：
- 开发板选 `ESP32 Dev Module`
- 串口选你的 ESP32 端口
- 上传

或用 Arduino CLI：

```bash
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/FakeCoyote
arduino-cli upload  --fqbn esp32:esp32:esp32 -p COM4 firmware/FakeCoyote
```

### 3. 启动抓包网页

```bash
cd capture
python capture_server.py
```

浏览器打开 <http://127.0.0.1:8765>。

若串口不是 COM4，可设环境变量 `DGLAB_SERIAL_PORT`（Linux/macOS 如 `/dev/ttyUSB0`）。

### 4. 抓包

用官方 App 扫描连接名为 `47L121000` 的设备，连接后随意调节强度/波形，
网页上即可实时看到指令与波形。

## 免责声明

本项目为逆向学习研究作品，不提供任何担保。使用者须自行确保遵守当地法律
及 DG-LAB 相关条款。严禁任何形式的商业使用与恶意用途。

**协议与商标版权归 DG-LAB（Dungeon Lab）及其 App 作者所有 · 严禁商用**
