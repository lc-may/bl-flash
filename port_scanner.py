"""
port_scanner.py
使用 pyserial 扫描当前可用串口
"""

from __future__ import annotations
import serial.tools.list_ports


def list_serial_ports() -> list[dict]:
    """
    返回当前所有可用串口信息列表。
    每项包含: port, description, hwid
    """
    ports = serial.tools.list_ports.comports()
    result = []
    for p in sorted(ports, key=lambda x: x.device):
        result.append({
            "port": p.device,
            "description": p.description,
            "hwid": p.hwid,
        })
    return result


if __name__ == "__main__":
    import json
    ports = list_serial_ports()
    if ports:
        print(json.dumps(ports, ensure_ascii=False, indent=2))
    else:
        print("未检测到任何串口")
