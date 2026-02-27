# BL Flash MCP Server

BL616/BL618 固件烧录 + UART 实时日志监控 MCP Server，基于 FastMCP + HTTP，供 WSL 内的 Claude Code 调用。

## 目录结构

```
D:\bouffalo_flash\
├── BLFlashCommand.exe     # 烧录工具（已有）
├── server.py              # MCP Server 主程序（5个Tools）
├── path_utils.py          # WSL↔Windows 路径转换
├── port_scanner.py        # 串口扫描（pyserial）
├── flash_runner.py        # 异步执行烧录 + 实时日志解析
├── uart_monitor.py        # UART 后台读取线程 + 10MB RingBuffer
├── config.json            # 配置文件
└── README.md
```

## 安装依赖

```powershell
pip install fastmcp pyserial
```

## 配置

编辑 `config.json`：

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `bl_flash_command` | BLFlashCommand.exe 完整路径 | `D:\bouffalo_flash\BLFlashCommand.exe` |
| `wsl_rootfs_drive` | WSL rootfs 挂载盘符 | `Z:` |
| `sse_port` | HTTP 监听端口 | `8765` |
| `flash_defaults.chipname` | 默认芯片型号 | `bl616` |
| `flash_defaults.baudrate` | 默认烧录波特率 | `2000000` |
| `flash_defaults.start_addr` | 默认烧录地址 | `0x10000` |
| `uart_defaults.baudrate` | UART 监控默认波特率 | `2000000` |
| `uart_ringbuffer_max_bytes` | RingBuffer 最大字节数 | `10485760`（10MB）|

## 启动 Server

```powershell
cd D:\bouffalo_flash
python server.py
```

## MCP Tools 说明

### 烧录相关

**`list_serial_ports`** — 列出所有可用串口，无需参数。

**`flash_firmware`** — 执行固件烧录。
```
file        固件路径（WSL路径或Windows路径）
port        串口号，如 COM6
start_addr  烧录地址，默认 0x10000
chipname    芯片型号，默认 bl616
baudrate    波特率，默认 2000000
```

### UART 监控相关

**`start_uart_monitor`** — 开启后台 UART 读取，录制到 10MB RingBuffer。
```
port        串口号，如 COM6
baudrate    波特率，默认从 config 读取
返回: session_id（后续操作需要）
```

**`read_uart_logs`** — 读取增量日志，最多 200 行/次。
```
session_id   start_uart_monitor 返回的 ID
since_index  上次返回的 new_index，首次传 0
返回: lines[], new_index, is_closed, is_error, total_lines
```

**`stop_uart_monitor`** — 停止监控，关闭串口。
```
session_id  要停止的 session ID
返回: total_lines, duration_seconds, dropped_lines
```

## Skill 文件部署

将 `skills/` 目录下的文件放到 Claude Code 项目中：

```
your_project/
├── .claude/
│   └── mcp.json                          # MCP 连接配置
└── skills/
    ├── bouffalo-build/SKILL.md           # 编译+烧录+监控主流程
    └── uart-log-analyzer/SKILL.md        # UART 分析 Sub-agent
```

`.claude/mcp.json`：
```json
{
  "mcpServers": {
    "bl-flash": {
      "type": "http",
      "url": "http://<Windows宿主IP>:8765/mcp"
    }
  }
}
```

## UART RingBuffer 设计

- 按行存储，超出 10MB 自动丢弃最旧行
- 全局单调递增行号（line_counter），支持增量读取
- 同一 port 不可重复开启 session
- 串口异常自动重试 3 次，失败后通过 `is_error` 通知 Sub-agent

