"""
uart_monitor.py
UART 后台读取线程 + 10MB RingBuffer + Session 管理

设计要点：
  - 每个 session 对应一个串口 + 一个后台线程
  - 日志按行存储在 deque 中，维护 total_bytes 控制 10MB 上限
  - line_counter 单调递增，外部通过 since_index 取增量日志
  - 线程安全：所有读写使用 threading.Lock
  - 同一 port 不允许重复开启
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Optional

import serial

logger = logging.getLogger("uart_monitor")

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

def _load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ── 每行日志条目 ───────────────────────────────────────────────
@dataclass
class LogLine:
    index: int        # 全局单调递增行号
    text: str         # 日志内容（已 strip 换行）
    timestamp: float  # time.time()


# ── UART Session ───────────────────────────────────────────────
class UartSession:
    def __init__(self, session_id: str, port: str, baudrate: int, max_bytes: int, encoding: str):
        self.session_id  = session_id
        self.port        = port
        self.baudrate    = baudrate
        self.max_bytes   = max_bytes
        self.encoding    = encoding

        self._lock        = threading.Lock()
        self._lines: deque[LogLine] = deque()
        self._total_bytes = 0           # 当前 buffer 占用字节数
        self._counter     = 0           # 下一行的 index（单调递增）
        self._dropped     = 0           # 因超出 10MB 被丢弃的行数

        self.is_closed    = False
        self.is_error     = False
        self.error_msg    = ""
        self.start_time   = time.time()

        self._serial: Optional[serial.Serial] = None
        self._thread  = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    # ── 后台读取线程 ──────────────────────────────────────────
    def _read_loop(self):
        retry = 0
        max_retry = 3

        while not self.is_closed:
            try:
                if self._serial is None or not self._serial.is_open:
                    self._serial = serial.Serial(
                        port=self.port,
                        baudrate=self.baudrate,
                        timeout=1.0,
                    )
                    retry = 0  # 成功连接，重置重试计数
                    logger.info("[%s] Serial port %s opened at %d baud", self.session_id, self.port, self.baudrate)

                raw = self._serial.readline()
                if not raw:
                    continue  # timeout，继续

                try:
                    text = raw.decode(self.encoding, errors="replace").rstrip("\r\n")
                except Exception:
                    text = repr(raw)

                if self._counter % 50 == 0:
                    logger.debug("[%s] UART rx line #%d: %r", self.session_id, self._counter, text[:80])

                self._append(text)

            except serial.SerialException as e:
                retry += 1
                logger.warning("[%s] SerialException (retry %d/%d): %s", self.session_id, retry, max_retry, e)
                self._append(f"[UART ERROR] {e}")
                if retry >= max_retry:
                    with self._lock:
                        self.is_error = True
                        self.error_msg = f"串口异常（重试{max_retry}次失败）: {e}"
                        self.is_closed = True
                    break
                time.sleep(0.5)

            except Exception as e:
                with self._lock:
                    self.is_error = True
                    self.error_msg = f"未知异常: {e}"
                    self.is_closed = True
                break

        # 线程退出时关闭串口
        try:
            if self._serial and self._serial.is_open:
                self._serial.close()
        except Exception:
            pass

    # ── 写入一行到 RingBuffer ────────────────────────────────
    def _append(self, text: str):
        line_bytes = len(text.encode(self.encoding, errors="replace")) + 1  # +1 换行

        with self._lock:
            entry = LogLine(
                index=self._counter,
                text=text,
                timestamp=time.time(),
            )
            self._counter += 1
            self._lines.append(entry)
            self._total_bytes += line_bytes

            # 超出 10MB 时从头部丢弃
            while self._total_bytes > self.max_bytes and self._lines:
                old = self._lines.popleft()
                old_bytes = len(old.text.encode(self.encoding, errors="replace")) + 1
                self._total_bytes -= old_bytes
                self._dropped += 1

            if self._counter % 50 == 0:
                logger.info(
                    "[%s] Buffer stats: total_lines=%d buffer=%.1fKB dropped=%d",
                    self.session_id, self._counter, self._total_bytes / 1024, self._dropped,
                )

    # ── 对外接口：取增量日志 ─────────────────────────────────
    def get_new_lines(
        self, since_index: int, max_lines: int = 200
    ) -> tuple[list[str], int, bool, bool, str]:
        """
        返回 since_index 之后的新日志（最多 max_lines 行）。

        Returns:
            lines      - 新日志文本列表
            new_index  - 下次调用传入的 since_index
            is_closed  - session 已停止
            is_error   - 串口异常
            error_msg  - 异常描述
        """
        with self._lock:
            result: list[str] = []
            result_last_index: Optional[int] = None

            oldest_index = self._lines[0].index if self._lines else self._counter
            effective_since = max(since_index, oldest_index)

            for entry in self._lines:
                if entry.index >= effective_since:
                    result.append(entry.text)
                    result_last_index = entry.index
                    if len(result) >= max_lines:
                        break

            if result_last_index is not None:
                new_index = result_last_index + 1
            else:
                # Keep index monotonic and jump to oldest available line after truncation.
                new_index = max(since_index, oldest_index)
            return result, new_index, self.is_closed, self.is_error, self.error_msg

    def is_active(self) -> bool:
        with self._lock:
            return (not self.is_closed) and self._thread.is_alive()

    # ── 停止 session ─────────────────────────────────────────
    def stop(self) -> dict:
        with self._lock:
            self.is_closed = True
            dropped = self._dropped
            total   = self._counter
        # 等待线程退出（最多 3 秒）
        self._thread.join(timeout=3.0)
        duration = round(time.time() - self.start_time, 1)
        logger.info(
            "[%s] Session stopped: total_lines=%d duration=%.1fs dropped=%d",
            self.session_id, total, duration, dropped,
        )
        return {
            "total_lines": total,
            "duration_seconds": duration,
            "dropped_lines": dropped,
        }


# ── 全局 Session 管理器 ────────────────────────────────────────
class SessionManager:
    def __init__(self):
        self._sessions: dict[str, UartSession] = {}
        self._lock = threading.Lock()

    def start(self, port: str, baudrate: int) -> tuple[str, str]:
        """
        开启新 session。
        返回 (session_id, error_msg)，error_msg 为空表示成功。
        """
        cfg = _load_config()
        max_bytes = cfg.get("uart_ringbuffer_max_bytes", 10 * 1024 * 1024)
        encoding  = cfg.get("uart_defaults", {}).get("encoding", "utf-8")

        with self._lock:
            stale_sids: list[str] = []
            # 检查同一 port 是否已有活跃 session
            for sid, sess in self._sessions.items():
                if not sess.is_active():
                    stale_sids.append(sid)
                    continue
                if sess.port == port:
                    return "", f"端口 {port} 已有活跃的监控 session（id={sid}），请先 stop 后再启动"

            for sid in stale_sids:
                self._sessions.pop(sid, None)

            session_id = str(uuid.uuid4())[:8]
            try:
                sess = UartSession(session_id, port, baudrate, max_bytes, encoding)
            except Exception as e:
                return "", f"打开串口 {port} 失败: {e}"

            self._sessions[session_id] = sess
            return session_id, ""

    def get(self, session_id: str) -> Optional[UartSession]:
        with self._lock:
            return self._sessions.get(session_id)

    def stop(self, session_id: str) -> tuple[dict, str]:
        """
        返回 (stats_dict, error_msg)
        """
        with self._lock:
            sess = self._sessions.get(session_id)
            if sess is None:
                return {}, f"session_id '{session_id}' 不存在"

        stats = sess.stop()

        with self._lock:
            self._sessions.pop(session_id, None)

        return stats, ""


# 全局单例
manager = SessionManager()
