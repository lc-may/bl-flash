# BL Flash MCP Server

BL616/BL618 固件烧录 MCP Server，基于 FastMCP + SSE，供 WSL 内的 Claude Code 调用。

## 目录结构

```
D:\bouffalo_flash\
├── BLFlashCommand.exe     # 烧录工具（已有）
├── server.py              # MCP Server 主程序
├── path_utils.py          # WSL↔Windows 路径转换
├── port_scanner.py        # 串口扫描（pyserial）
├── flash_runner.py        # 异步执行烧录 + 实时日志解析
├── config.json            # 配置文件
└── README.md
```

## 安装依赖

在 Windows PowerShell 中执行：

```powershell
pip install fastmcp pyserial
```

## 配置

编辑 `config.json`，确认以下字段：

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `bl_flash_command` | BLFlashCommand.exe 完整路径 | `D:\bouffalo_flash\BLFlashCommand.exe` |
| `wsl_rootfs_drive` | WSL rootfs 挂载盘符 | `Z:` |
| `sse_port` | SSE 监听端口 | `8765` |
| `flash_defaults.chipname` | 默认芯片型号 | `bl616` |
| `flash_defaults.baudrate` | 默认波特率 | `2000000` |
| `flash_defaults.start_addr` | 默认烧录地址 | `0x10000` |

## 启动 Server

```powershell
cd D:\bouffalo_flash
python server.py
```

启动后输出：
```
[BL Flash MCP] 启动 SSE 服务: http://0.0.0.0:8765/sse
```

## WSL Claude Code 配置

在 WSL 项目根目录创建 `.claude/mcp.json`：

```json
{
  "mcpServers": {
    "bl-flash": {
      "type": "sse",
      "url": "http://<Windows宿主IP>:8765/sse"
    }
  }
}
```

获取 Windows 宿主 IP：
```bash
cat /etc/resolv.conf | grep nameserver | awk '{print $2}'
```

## MCP Tools 说明

### `list_serial_ports`
列出当前所有可用串口。无需参数。

### `list_files`
列出指定目录下所有 `.bin` 文件，供选择固件。

```
参数: directory_path  支持 WSL 路径或 Windows 路径
```

### `flash_firmware`
执行固件烧录。

```
参数:
  file        固件路径（WSL路径或Windows路径）
  port        串口号，如 COM6
  start_addr  烧录地址，默认 0x10000
  chipname    芯片型号，默认 bl616
  baudrate    波特率，默认 2000000
```

## 开机自启（Windows Task Scheduler）

1. 打开"任务计划程序"
2. 创建基本任务，触发器选"登录时"
3. 操作选"启动程序"
4. 程序填：`python`，参数填：`D:\bouffalo_flash\server.py`
5. 勾选"无论用户是否登录都要运行"

或使用 NSSM 注册为 Windows 服务：
```powershell
nssm install BLFlashMCP python D:\bouffalo_flash\server.py
nssm start BLFlashMCP
```

## 注意事项

- **路径转换**：`/home/leo/...` 自动转为 `Z:\home\leo\...`，`/mnt/c/...` 自动转为 `C:\...`
- **成功判断**：检测日志中 `"All programming completed successfully"` 关键词
- **失败原因**：自动提取包含 Error/failed/timeout 的日志行
- **超时保护**：默认 120 秒，可在 `config.json` 中调整 `flash_timeout_seconds`
