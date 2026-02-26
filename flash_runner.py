"""
flash_runner.py
异步执行 BLFlashCommand.exe，实时读取日志，解析成功/失败结果
"""

from __future__ import annotations
import asyncio
import json
import os
import re
from dataclasses import dataclass, field

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def _load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@dataclass
class FlashResult:
    success: bool
    logs: list[str] = field(default_factory=list)
    error_reason: str = ""
    progress_final: int = 0  # 最后一次进度百分比

    def full_log(self) -> str:
        return "\n".join(self.logs)

    def summary(self) -> str:
        status = "✅ 烧录成功" if self.success else "❌ 烧录失败"
        lines = [status]
        if self.success:
            lines.append(f"进度: {self.progress_final}%")
        else:
            lines.append(f"失败原因: {self.error_reason or '未知'}")
        lines.append("")
        lines.append("=== 完整日志 ===")
        lines.append(self.full_log())
        return "\n".join(lines)


# 进度行正则: "Load  2048/60408 [3%]"
_PROGRESS_RE = re.compile(r"Load\s+\d+/\d+\s+\[(\d+)%\]")


async def run_flash(
    firmware_path: str,
    port: str,
    start_addr: str | None = None,
    chipname: str | None = None,
    baudrate: int | None = None,
    interface: str | None = None,
) -> FlashResult:
    """
    异步执行 BLFlashCommand.exe 并实时解析日志。
    参数为 None 时从 config.json 读取默认值。
    """
    cfg = _load_config()
    exe = cfg["bl_flash_command"]
    defaults = cfg.get("flash_defaults", {})
    timeout = cfg.get("flash_timeout_seconds", 120)
    success_kws = cfg.get("success_keywords", ["All programming completed successfully"])
    failure_kws = cfg.get("failure_keywords", ["Error", "failed", "timeout"])

    chipname  = chipname  or defaults.get("chipname",   "bl616")
    baudrate  = baudrate  or defaults.get("baudrate",   2000000)
    interface = interface or defaults.get("interface",  "uart")
    start_addr= start_addr or defaults.get("start_addr","0x10000")

    cmd = [
        exe,
        f"--interface={interface}",
        f"--chipname={chipname}",
        f"--port={port}",
        f"--baudrate={baudrate}",
        "--flash",
        "--write",
        f"--start={start_addr}",
        f"--file={firmware_path}",
    ]

    result = FlashResult(success=False)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # 合并 stderr 到 stdout
        )

        async def read_output():
            assert proc.stdout is not None
            while True:
                line_bytes = await proc.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").rstrip()
                result.logs.append(line)

                # 解析进度
                m = _PROGRESS_RE.search(line)
                if m:
                    result.progress_final = int(m.group(1))

                # 检测失败关键词（提取原因）
                if not result.success:
                    for kw in failure_kws:
                        if kw in line:
                            if not result.error_reason:
                                result.error_reason = line.strip()
                            break

                # 检测成功关键词
                for kw in success_kws:
                    if kw in line:
                        result.success = True
                        break

        await asyncio.wait_for(read_output(), timeout=timeout)
        await proc.wait()

        # 进程返回值兜底
        if proc.returncode != 0 and result.success:
            result.success = False
            result.error_reason = f"进程返回非零退出码: {proc.returncode}"

    except asyncio.TimeoutError:
        result.error_reason = f"烧录超时（>{timeout}s），请检查串口连接和设备状态"
        try:
            proc.kill()
        except Exception:
            pass

    except FileNotFoundError:
        result.error_reason = f"BLFlashCommand.exe 未找到: {exe}"

    except Exception as e:
        result.error_reason = f"执行异常: {e}"

    return result
