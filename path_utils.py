"""
path_utils.py
WSL路径 <-> Windows路径 转换工具

支持：
  /mnt/c/foo/bar   -> C:\\foo\\bar
  /home/leo/foo    -> Z:\\home\\leo\\foo   (rootfs盘符从config读取)
  C:\\foo\\bar      -> 原样返回
"""

import json
import os

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

def _load_rootfs_drive() -> str:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg.get("wsl_rootfs_drive", "Z:").rstrip("\\")


def wsl_to_windows(path: str) -> str:
    """
    将 WSL 路径转换为 Windows 路径。
    已是 Windows 路径（含盘符）则直接返回。
    """
    # 已是 Windows 路径
    if len(path) >= 2 and path[1] == ":":
        return path

    # /mnt/x/... -> X:\\...
    if path.startswith("/mnt/"):
        parts = path[5:].split("/", 1)
        drive = parts[0].upper() + ":\\"
        rest = parts[1].replace("/", "\\") if len(parts) > 1 else ""
        return drive + rest

    # /home/... /root/... 等 WSL rootfs 路径
    rootfs_drive = _load_rootfs_drive()
    win_path = path.replace("/", "\\")
    return rootfs_drive + win_path


def windows_to_wsl(path: str) -> str:
    """
    将 Windows 路径转换为 WSL 路径（辅助用途）。
    """
    rootfs_drive = _load_rootfs_drive().upper()

    # Z:\\home\\... -> /home/...
    if path.upper().startswith(rootfs_drive):
        rest = path[len(rootfs_drive):]
        return rest.replace("\\", "/")

    # C:\\foo -> /mnt/c/foo
    if len(path) >= 2 and path[1] == ":":
        drive_letter = path[0].lower()
        rest = path[2:].replace("\\", "/")
        return f"/mnt/{drive_letter}{rest}"

    return path


if __name__ == "__main__":
    # 简单测试
    cases = [
        "/mnt/c/Users/leo/firmware.bin",
        "/home/leo/bouffalo_sdk/build/out/app.bin",
        "Z:\\home\\leo\\app.bin",
        "C:\\Users\\leo\\firmware.bin",
    ]
    for c in cases:
        print(f"{c}  ->  {wsl_to_windows(c)}")
