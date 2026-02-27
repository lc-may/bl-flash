"""
server.py
BL616/BL618 固件烧录 + UART 监控 MCP Server（FastMCP，HTTP 模式）

Tools:
  - list_serial_ports   : 列出可用 COM 口
  - flash_firmware      : 执行固件烧录
  - start_uart_monitor  : 开启 UART 后台监控（RingBuffer 录制）
  - read_uart_logs      : 读取增量日志（最多 200 行/次）
  - stop_uart_monitor   : 停止监控，返回统计信息
"""

from __future__ import annotations
import json
import logging
import os
import time
from pathlib import Path

from fastmcp import FastMCP
from path_utils import wsl_to_windows
from port_scanner import list_serial_ports as _scan_ports
from flash_runner import run_flash
from uart_monitor import manager as _uart_manager

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("mcp_server")

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

def _cfg() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

mcp = FastMCP("bl-flash-server")


@mcp.tool()
def list_serial_ports() -> str:
    """
    列出当前系统所有可用串口（COM 口）。
    返回 JSON 数组，每项包含 port、description、hwid。
    """
    ports = _scan_ports()
    if not ports:
        return "未检测到任何串口，请确认设备已连接。"
    return json.dumps(ports, ensure_ascii=False, indent=2)


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
    win_file = wsl_to_windows(file)
    if not Path(win_file).exists():
        return f"❌ 固件文件不存在: {win_file}\n（原始路径: {file}）"
    result = await run_flash(
        firmware_path=win_file,
        port=port,
        start_addr=start_addr,
        chipname=chipname,
        baudrate=baudrate,
    )
    return result.summary()


@mcp.tool()
def start_uart_monitor(
    port: str,
    baudrate: int | None = None,
) -> str:
    """
    开启 UART 后台监控，开始将串口输出录制到内存 RingBuffer（最大 10MB）。

    参数：
      port     - 串口号，如 COM6
      baudrate - 波特率，默认从 config.json 读取（通常 2000000）

    返回 session_id，后续 read_uart_logs / stop_uart_monitor 均需要此 ID。
    同一 port 不可重复开启，请先 stop 后再启动。
    """
    cfg = _cfg()
    if baudrate is None:
        baudrate = cfg.get("uart_defaults", {}).get("baudrate", 2000000)

    session_id, err = _uart_manager.start(port, baudrate)
    if err:
        return f"❌ 启动失败: {err}"

    logger.info("[start_uart_monitor] port=%s baudrate=%d -> session=%s", port, baudrate, session_id)
    result = {
        "session_id": session_id,
        "port": port,
        "baudrate": baudrate,
        "start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "message": f"✅ UART 监控已启动，session_id={session_id}",
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def read_uart_logs(
    session_id: str,
    since_index: int,
) -> str:
    """
    读取 UART 监控的增量日志。每次最多返回 200 行。

    参数：
      session_id  - start_uart_monitor 返回的 session ID
      since_index - 上次返回的 new_index（首次调用传 0）

    返回 JSON：
      lines       - 本次新增日志行数组
      new_index   - 下次调用传入的 since_index
      is_closed   - true 表示 session 已停止，Sub-agent 应退出 loop
      is_error    - true 表示串口发生异常
      error_msg   - 异常描述
      total_lines - 本 session 累计接收总行数
    """
    sess = _uart_manager.get(session_id)
    if sess is None:
        return json.dumps({
            "lines": [],
            "new_index": since_index,
            "is_closed": True,
            "is_error": True,
            "error_msg": f"session_id '{session_id}' 不存在或已被清理",
            "total_lines": 0,
        }, ensure_ascii=False)

    lines, new_index, is_closed, is_error, error_msg = sess.get_new_lines(
        since_index=since_index,
        max_lines=200,
    )
    logger.info(
        "[read_uart_logs] session=%s since=%d -> got=%d new_index=%d closed=%s error=%s",
        session_id, since_index, len(lines), new_index, is_closed, is_error,
    )
    result = {
        "lines": lines,
        "new_index": new_index,
        "is_closed": is_closed,
        "is_error": is_error,
        "error_msg": error_msg,
        "total_lines": sess._counter,
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def stop_uart_monitor(session_id: str) -> str:
    """
    停止 UART 监控，关闭串口，释放资源。

    参数：
      session_id - start_uart_monitor 返回的 session ID

    返回统计信息：总行数、运行时长、因超出 10MB 被丢弃的行数。
    """
    stats, err = _uart_manager.stop(session_id)
    if err:
        return f"❌ 停止失败: {err}"
    logger.info("[stop_uart_monitor] session=%s stats=%s", session_id, stats)
    result = {
        "message": "✅ UART 监控已停止",
        "session_id": session_id,
        **stats,
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    cfg = _cfg()
    host = cfg.get("sse_host", "0.0.0.0")
    port = cfg.get("sse_port", 8765)
    print(f"[BL Flash MCP] starting HTTP server: http://{host}:{port}/mcp")
    mcp.run(
        transport="http",
        host=host,
        port=port,
    )
