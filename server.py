"""
server.py
BL616/BL618 固件烧录 MCP Server（FastMCP，HTTP模式）

Tools:
  - list_serial_ports : 列出可用COM口
  - flash_firmware    : 执行固件烧录
"""

from __future__ import annotations
import json
import os
from pathlib import Path

from fastmcp import FastMCP
from path_utils import wsl_to_windows
from port_scanner import list_serial_ports as _scan_ports
from flash_runner import run_flash

# ── 读取配置 ────────────────────────────────────────────────────
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

def _cfg() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

# ── FastMCP 实例 ────────────────────────────────────────────────
cfg = _cfg()
mcp = FastMCP("bl-flash-server")

# ── Tool 1: list_serial_ports ───────────────────────────────────
@mcp.tool()
def list_serial_ports() -> str:
    """
    列出当前系统所有可用串口（COM口）。
    返回 JSON 数组，每项包含 port、description、hwid。
    """
    ports = _scan_ports()
    if not ports:
        return "未检测到任何串口，请确认设备已连接。"
    return json.dumps(ports, ensure_ascii=False, indent=2)


# ── Tool 2: flash_firmware ──────────────────────────────────────
@mcp.tool()
async def flash_firmware(
    file: str,
    port: str,
    start_addr: str | None = None,
    chipname: str | None = None,
    baudrate: int | None = None,
) -> str:
    """
    烧录固件到 BL616/BL618。

    参数：
      file       - 固件路径，支持 WSL 路径（/home/...、/mnt/c/...）或 Windows 路径
      port       - 串口号，如 COM6
      start_addr - 烧录起始地址，默认 0x10000（从 config.json 读取）
      chipname   - 芯片型号，默认 bl616
      baudrate   - 波特率，默认 2000000

    返回烧录结果摘要和完整日志。
    """
    # 路径转换
    win_file = wsl_to_windows(file)

    # 检查文件是否存在
    if not Path(win_file).exists():
        return f"❌ 固件文件不存在: {win_file}\n（原始路径: {file}）"

    # 执行烧录
    result = await run_flash(
        firmware_path=win_file,
        port=port,
        start_addr=start_addr,
        chipname=chipname,
        baudrate=baudrate,
    )

    return result.summary()


# ── 启动 ────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"[BL Flash MCP] starting HTTP server: http://{cfg.get('sse_host','0.0.0.0')}:{cfg.get('sse_port',8765)}/mcp")
    mcp.run(
        transport="http",
        host=cfg.get("sse_host", "0.0.0.0"),
        port=cfg.get("sse_port", 8765),
    )
