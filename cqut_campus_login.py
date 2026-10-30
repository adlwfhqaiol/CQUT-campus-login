#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重庆理工大学锐捷 ePortal 自动认证工具。

只使用 Python 标准库。账号密码默认以 Windows DPAPI 加密后保存，
加密内容只能由当前 Windows 用户解密。
"""

from __future__ import annotations

import argparse
import base64
import ctypes
from ctypes import wintypes
import getpass
import hashlib
import html
import http.cookiejar
import json
import os
from pathlib import Path
import random
import re
import secrets
import shutil
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib


APP_NAME = "CQUT Campus Login"
__version__ = "1.1.0"
TASK_NAME = "CQUT Campus Auto Login"
DEFAULT_PORTAL = "http://202.202.145.132"
PORTAL_HOST = "202.202.145.132"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/132.0.0.0 Safari/537.36"
)
DEFAULT_SETTINGS = {
    "portal_candidates": [
        DEFAULT_PORTAL,
        "http://202.202.145.132:8080",
    ],
    "service": "auto",
    "service_keyword": "移动",
    "check_interval": 60,
    "warmup_seconds": 180,
    "request_timeout": 8,
    "max_captcha_attempts": 6,
    "password_length": 10,
    "post_login_wait_seconds": 240,
}

# Edge 登录助手的结果：只有前两种表示已经向学校提交过认证。
# 提交后门户往往还要一段时间才放行，这段时间里不能再开新的登录会话，
# 否则会制造互相冲突的会话，反而拖慢放行。
EDGE_SUCCESS = "success"
EDGE_SUBMITTED = "submitted"
EDGE_NO_FORM = "no-form"
EDGE_UNAVAILABLE = "unavailable"

PROBES = (
    ("http://connect.rom.miui.com/generate_204", 204, None),
    ("http://edge.microsoft.com/captiveportal/generate_204", 204, None),
    ("http://www.msftconnecttest.com/connecttest.txt", 200, "Microsoft Connect Test"),
)
SSO_PUBLIC_KEY = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDACwPDxYycdCiNeblZa9LjvDzb"
    "iZU1vc9gKRcG/pGjZ/DJkI4HmoUE2r/o6SfB5az3s+H5JDzmOMVQ63hD7LZQGR4k"
    "3iYWnCg3UpQZkZEtFtXBXsQHjKVJqCiEtK+gtxz4WnriDjf+e/CxJ7OD03e7sy5N"
    "Y/akVmYNtghKZzz6jwIDAQAB"
)
SSO_UNIVERSITY_ID = "100005"
SSO_LOGIN_ENDPOINT = "https://uis.cqut.edu.cn/center-auth-server/sso/doLogin"

# 重庆理工大学当前 80x30 验证码门体的十个精确字形。
# 采集到的 20 张样本全部命中这十个位图，字形本身没有随机变形。
CAPTCHA_GLYPHS = {
    "9": (
        "....#####....",
        "..###...##...",
        ".###.....##..",
        ".##......###.",
        "###.......##.",
        "###.......###",
        "###.......###",
        "###.......###",
        "####......###",
        ".###......###",
        "..###....####",
        "...######.##.",
        ".........###.",
        ".........##..",
        "........###..",
        ".......###...",
        "......###....",
        ".....###.....",
        "...###.......",
        "####.........",
    ),
    "1": (
        "....##...",
        ".#####...",
        "######...",
        "...###...",
        "...###...",
        "...###...",
        "...###...",
        "...###...",
        "...###...",
        "...###...",
        "...###...",
        "...###...",
        "...###...",
        "...###...",
        "...###...",
        "...###...",
        "...###...",
        "...###...",
        "...###...",
        "#########",
    ),
    "6": (
        ".........####",
        ".......###...",
        ".....###.....",
        "....###......",
        "...###.......",
        "..###........",
        "..##.........",
        ".###.........",
        ".##..#####...",
        "#####...###..",
        "###......###.",
        "###......####",
        "###.......###",
        "###.......###",
        "###.......###",
        ".##.......###",
        ".###......##.",
        "..##.....###.",
        "...##...###..",
        "....#####....",
    ),
    "0": (
        ".....####....",
        "...##...##...",
        "..##.....##..",
        "..##.....###.",
        ".###......##.",
        ".##.......##.",
        "###.......###",
        "###.......###",
        "###.......###",
        "###.......###",
        "###.......###",
        "###.......###",
        "###.......###",
        "###.......###",
        ".##.......##.",
        ".###.....###.",
        ".###.....###.",
        "..##.....##..",
        "...##...##...",
        "....####.....",
    ),
    "5": (
        "....#######",
        "...#######.",
        "...#######.",
        "..#........",
        "..#........",
        ".####......",
        ".######....",
        "#########..",
        "....######.",
        "......####.",
        ".......####",
        "........###",
        ".........##",
        ".........##",
        ".........##",
        ".........#.",
        "........##.",
        ".#.....##..",
        "########...",
        ".#####.....",
    ),
    "4": (
        "........##...",
        ".......###...",
        "......####...",
        "......####...",
        ".....#.###...",
        ".....#.###...",
        "....#..###...",
        "...#...###...",
        "...#...###...",
        "..#....###...",
        "..#....###...",
        ".#.....###...",
        "##.....###...",
        "#############",
        "#############",
        ".......###...",
        ".......###...",
        ".......###...",
        ".......###...",
        ".......###...",
    ),
    "7": (
        "..###########",
        ".############",
        ".###########.",
        ".#........##.",
        "#........##..",
        ".........##..",
        ".........##..",
        "........##...",
        "........##...",
        "........##...",
        ".......##....",
        ".......##....",
        ".......##....",
        "......##.....",
        "......##.....",
        "......##.....",
        ".....##......",
        ".....##......",
        ".....##......",
        "....##.......",
    ),
    "8": (
        "...#####...",
        ".###...###.",
        ".##.....###",
        "###.....###",
        "###.....###",
        "###.....###",
        "####...###.",
        ".####..##..",
        "..#####....",
        "...####....",
        "...#####...",
        "..##.####..",
        ".##...####.",
        "###....####",
        "###.....###",
        "###.....###",
        "###.....###",
        ".##.....##.",
        ".###...###.",
        "...#####...",
    ),
    "3": (
        "...######...",
        "..########..",
        ".#.....####.",
        "#.......###.",
        "........###.",
        "........###.",
        "........##..",
        ".......##...",
        ".....####...",
        "...#######..",
        "......#####.",
        "........####",
        "........####",
        ".........###",
        ".........###",
        ".........###",
        ".........##.",
        "##......##..",
        "####...##...",
        ".######.....",
    ),
    "2": (
        "...######....",
        "..########...",
        ".##....####..",
        "#.......####.",
        "#........###.",
        ".........###.",
        ".........###.",
        ".........##..",
        ".........##..",
        "........##...",
        "........##...",
        ".......##....",
        "......##.....",
        "......#......",
        ".....#.......",
        "....#........",
        "...##.......#",
        "..##.......##",
        ".###########.",
        "############.",
    ),
}
CAPTCHA_TEMPLATES = {
    hashlib.sha256(
        "\n".join(row.replace("#", "1").replace(".", "0") for row in rows).encode("ascii")
    ).hexdigest(): digit
    for digit, rows in CAPTCHA_GLYPHS.items()
}


class LoginError(RuntimeError):
    pass


class CredentialError(LoginError):
    pass


class PendingReleaseError(LoginError):
    """凭据已通过认证，但门户/AC 尚未放行。"""


class Session:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self.cookies),
            self.NoRedirect(),
        )

    def request(
        self,
        url: str,
        method: str = "GET",
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> "WebResponse":
        request_headers = {
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Connection": "close",
        }
        if headers:
            request_headers.update(headers)
        req = urllib.request.Request(url, data=data, headers=request_headers, method=method)
        try:
            response = self.opener.open(req, timeout=self.timeout)
            body = response.read(2 * 1024 * 1024)
            return WebResponse(response.status, response.geturl(), response.headers, body)
        except urllib.error.HTTPError as exc:
            body = exc.read(2 * 1024 * 1024)
            return WebResponse(exc.code, exc.geturl(), exc.headers, body)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LoginError(f"网络请求失败：{exc}") from exc


class WebResponse:
    def __init__(self, status: int, url: str, headers, body: bytes) -> None:
        self.status = status
        self.url = url
        self.headers = headers
        self.body = body

    @property
    def location(self) -> str:
        return self.headers.get("Location", "")

    @property
    def text(self) -> str:
        content_type = self.headers.get("Content-Type", "")
        match = re.search(r"charset=([\w-]+)", content_type, re.I)
        encodings = []
        if match:
            encodings.append(match.group(1))
        encodings.extend(("utf-8", "gb18030"))
        for encoding in encodings:
            try:
                return self.body.decode(encoding)
            except (LookupError, UnicodeDecodeError):
                continue
        return self.body.decode("utf-8", "replace")


def data_dir() -> Path:
    override = os.environ.get("CQUT_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "CQUTCampusLogin"
    return Path.home() / ".config" / "cqut-campus-login"


SETTINGS_PATH = data_dir() / "settings.json"
CREDENTIALS_PATH = data_dir() / "credentials.bin"
LOG_PATH = data_dir() / "login.log"
LOCK_PATH = data_dir() / "watch.lock"
_watch_mutex = None


def startup_vbs_path() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return (
        Path(appdata)
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / "CQUT Campus Auto Login.vbs"
    )


class Logger:
    def __init__(self, quiet: bool = False, path: Path | None = None) -> None:
        self.quiet = quiet
        self.path = path or LOG_PATH

    def write(self, message: str, level: str = "INFO") -> None:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        # 门户返回内容属于外部输入。压平换行和控制字符，避免伪造日志行。
        clean_message = re.sub(r"[\x00-\x1f\x7f]+", " ", str(message)).strip()
        line = f"[{stamp}] [{level}] {clean_message}"
        if not self.quiet or level in ("WARN", "ERROR"):
            print(line, flush=True)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size > 1024 * 1024:
                backup = self.path.with_suffix(".old.log")
                os.replace(self.path, backup)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            pass


if os.name == "nt":
    class DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    _crypt32.CryptProtectData.restype = wintypes.BOOL
    _crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel32.CreateMutexW.restype = wintypes.HANDLE


def _blob(data: bytes) -> "DataBlob":
    buffer = ctypes.create_string_buffer(data)
    return DataBlob(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)),
    )


def protect_bytes(data: bytes) -> bytes:
    if os.name != "nt":
        raise LoginError(
            "当前系统不支持 Windows DPAPI 安全凭据存储。"
            "请通过 CQUT_USERNAME 和 CQUT_PASSWORD 环境变量提供凭据。"
        )
    entropy = _blob(b"CQUT Campus Login v1")
    source = _blob(data)
    output = DataBlob()
    ok = _crypt32.CryptProtectData(
        ctypes.byref(source),
        APP_NAME,
        ctypes.byref(entropy),
        None,
        None,
        0x1,
        ctypes.byref(output),
    )
    if not ok:
        raise LoginError(f"Windows 凭据加密失败（{ctypes.get_last_error()}）")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        _kernel32.LocalFree(output.pbData)


def unprotect_bytes(data: bytes) -> bytes:
    if data.startswith(b"RAW:"):
        raise LoginError(
            "检测到旧版明文凭据，已拒绝读取。"
            "请删除 credentials.bin，然后重新运行 --init；"
            "非 Windows 系统请改用环境变量。"
        )
    if os.name != "nt":
        raise LoginError("当前系统没有可用的安全凭据存储")
    entropy = _blob(b"CQUT Campus Login v1")
    source = _blob(data)
    output = DataBlob()
    ok = _crypt32.CryptUnprotectData(
        ctypes.byref(source),
        None,
        ctypes.byref(entropy),
        None,
        None,
        0x1,
        ctypes.byref(output),
    )
    if not ok:
        raise LoginError(
            "账号密码解密失败。请运行 --init 重新保存；"
            "DPAPI 凭据只能由保存它的 Windows 用户解密。"
        )
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        _kernel32.LocalFree(output.pbData)


def process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        handle = _kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        _kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_watch_lock() -> bool:
    global _watch_mutex
    if os.name == "nt":
        ctypes.set_last_error(0)
        handle = _kernel32.CreateMutexW(
            None,
            False,
            "Local\\CQUTCampusLoginWatch",
        )
        if not handle:
            return False
        if ctypes.get_last_error() == 183:
            _kernel32.CloseHandle(handle)
            return False
        _watch_mutex = handle
        return True
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            descriptor = os.open(
                LOCK_PATH,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
            with os.fdopen(descriptor, "w", encoding="ascii") as handle:
                handle.write(str(os.getpid()))
            return True
        except FileExistsError:
            try:
                pid = int(LOCK_PATH.read_text(encoding="ascii").strip())
            except (OSError, ValueError):
                pid = 0
            if process_is_alive(pid):
                return False
            try:
                LOCK_PATH.unlink()
            except OSError:
                return False
    return False


def release_watch_lock() -> None:
    global _watch_mutex
    if os.name == "nt" and _watch_mutex:
        _kernel32.CloseHandle(_watch_mutex)
        _watch_mutex = None
        return
    try:
        LOCK_PATH.unlink()
    except OSError:
        pass


def atomic_write_bytes(path: Path, data: bytes, mode: int = 0o600) -> None:
    """在目标文件同目录写入临时文件后原子替换。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            path.parent.chmod(0o700)
        except OSError:
            pass
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            try:
                temporary.chmod(mode)
            except OSError:
                pass
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def bounded_int(settings: dict, key: str, minimum: int, maximum: int) -> int:
    default = int(DEFAULT_SETTINGS[key])
    try:
        value = int(settings.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def normalize_settings(settings: dict) -> dict:
    normalized = dict(DEFAULT_SETTINGS)
    if isinstance(settings, dict):
        normalized.update(settings)

    candidates = normalized.get("portal_candidates")
    if isinstance(candidates, str):
        candidates = [candidates]
    if not isinstance(candidates, list):
        candidates = list(DEFAULT_SETTINGS["portal_candidates"])
    normalized["portal_candidates"] = [
        str(value).strip()
        for value in candidates[:10]
        if str(value).strip()
    ] or list(DEFAULT_SETTINGS["portal_candidates"])

    for key in ("service", "service_keyword"):
        normalized[key] = str(normalized.get(key, DEFAULT_SETTINGS[key])).strip()

    normalized["check_interval"] = bounded_int(normalized, "check_interval", 20, 3600)
    normalized["warmup_seconds"] = bounded_int(normalized, "warmup_seconds", 0, 3600)
    normalized["request_timeout"] = bounded_int(normalized, "request_timeout", 2, 30)
    normalized["max_captcha_attempts"] = bounded_int(
        normalized, "max_captcha_attempts", 1, 20
    )
    normalized["password_length"] = bounded_int(normalized, "password_length", 1, 128)
    normalized["post_login_wait_seconds"] = bounded_int(
        normalized, "post_login_wait_seconds", 5, 600
    )
    return normalized


def save_settings(settings: dict) -> None:
    merged = dict(DEFAULT_SETTINGS)
    merged.update(settings)
    merged = normalize_settings(merged)
    atomic_write_bytes(
        SETTINGS_PATH,
        (json.dumps(merged, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    if SETTINGS_PATH.exists():
        try:
            loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                settings.update(loaded)
        except (OSError, ValueError) as exc:
            raise LoginError(f"配置读取失败：{exc}") from exc
    return normalize_settings(settings)


def save_credentials(username: str, password: str) -> None:
    if os.name != "nt":
        raise LoginError(
            "当前系统不支持 Windows DPAPI 安全凭据存储。"
            "请设置 CQUT_USERNAME 和 CQUT_PASSWORD 环境变量。"
        )
    payload = json.dumps(
        {"username": username, "password": password},
        ensure_ascii=False,
    ).encode("utf-8")
    atomic_write_bytes(CREDENTIALS_PATH, protect_bytes(payload))


def load_credentials() -> tuple[str, str]:
    env_user = os.environ.get("CQUT_USERNAME", "").strip()
    env_password = os.environ.get("CQUT_PASSWORD", "")
    if env_user and env_password:
        return env_user, env_password
    if not CREDENTIALS_PATH.exists():
        raise LoginError("还没有保存账号密码，请先运行：py -3 cqut_campus_login.py --init")
    try:
        payload = json.loads(unprotect_bytes(CREDENTIALS_PATH.read_bytes()).decode("utf-8"))
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", ""))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise LoginError(f"凭据读取失败：{exc}") from exc
    if not username or not password:
        raise LoginError("保存的账号或密码为空，请重新运行 --init")
    return username, password


def initialize(settings: dict, logger: Logger) -> None:
    print("重庆理工大学校园网配置")
    print("账号为统一身份认证账号；密码不会显示，也不会写入明文配置。")
    username = input("账号：").strip()
    if not username:
        raise LoginError("账号不能为空")
    expected_length = int(settings.get("password_length", 10))
    while True:
        password = getpass.getpass(
            f"密码（应为 {expected_length} 位，输入时不显示）："
        )
        print(f"本次输入长度：{len(password)} 个字符（仅显示长度，不显示密码）")
        if len(password) != expected_length:
            print(
                f"长度不是 {expected_length} 位，本次不保存。"
                "请按 Ctrl+C 退出，或重新输入。"
            )
            continue
        confirmation = getpass.getpass("再次输入密码确认：")
        if password != confirmation:
            print("两次输入的密码不一致，本次不保存，请重新输入。")
            continue
        break
    service_keyword = input(
        f"运营商/服务关键字 [{settings.get('service_keyword', '移动')}]："
    ).strip()
    settings["service_keyword"] = service_keyword or settings.get("service_keyword", "移动")
    save_settings(settings)
    save_credentials(username, password)
    logger.write(f"配置已保存到 {data_dir()}", "OK")


def check_online(session: Session) -> tuple[bool, str]:
    portal_hint = ""
    last_error = ""
    for url, expected_status, marker in PROBES:
        try:
            response = session.request(url)
        except LoginError as exc:
            last_error = str(exc)
            continue
        location = response.location
        if location:
            portal_hint = urllib.parse.urljoin(response.url, location)
        if response.status == expected_status and not location:
            if marker is None or marker.lower() in response.text.lower():
                return True, portal_hint
        last_error = f"{url} 返回 HTTP {response.status}"
    return False, portal_hint


def find_portal_location(session: Session, settings: dict) -> tuple[str, str]:
    candidates: list[str] = []

    for probe_url, _, _ in PROBES:
        try:
            response = session.request(probe_url)
        except LoginError:
            continue
        location = urllib.parse.urljoin(response.url, response.location) if response.location else ""
        location_host = (urllib.parse.urlsplit(location).hostname or "").lower()
        if "/eportal/" in location.lower() and is_trusted_school_host(location_host):
            candidates.append(location)
        text = response.text
        for match in re.finditer(r"https?://[^\"'\s<>]+", text, re.I):
            url = html.unescape(match.group(0))
            url_host = (urllib.parse.urlsplit(url).hostname or "").lower()
            if "/eportal/" in url.lower() and is_trusted_school_host(url_host):
                candidates.append(url)

    for raw_origin in settings.get("portal_candidates", []):
        origin = normalize_origin(raw_origin)
        if not origin:
            continue
        current = origin + "/"
        for _ in range(5):
            try:
                response = session.request(current)
            except LoginError:
                break
            if not response.location:
                break
            current = urllib.parse.urljoin(current, html.unescape(response.location))
            current_host = (urllib.parse.urlsplit(current).hostname or "").lower()
            if "/eportal/" in current.lower() and is_trusted_school_host(current_host):
                candidates.append(current)
            if "success.jsp" in current.lower():
                break

    for location in candidates:
        query = extract_query_string(location)
        if query and "wlanuserip" in query.lower():
            return location, query
    raise LoginError(
        "没有拿到 AC 下发的登录参数。请确认当前连接的是重庆理工大学有线网或校园 Wi-Fi。"
    )


def normalize_origin(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "http://" + value
    parts = urllib.parse.urlsplit(value)
    if not parts.netloc:
        return ""
    scheme = "http" if (parts.hostname or "").lower() == PORTAL_HOST else parts.scheme
    return f"{scheme}://{parts.netloc}"


def extract_query_string(location: str) -> str:
    parts = urllib.parse.urlsplit(html.unescape(location))
    return parts.query


def login_page_url(location: str, query: str) -> str:
    origin = normalize_origin(location)
    parts = urllib.parse.urlsplit(location)
    if "index.jsp" in parts.path:
        return urllib.parse.urlunsplit(
            (
                "http" if (parts.hostname or "").lower() == PORTAL_HOST else parts.scheme,
                parts.netloc,
                parts.path,
                query,
                "",
            )
        )
    return origin + "/eportal/index.jsp?" + query


def parse_inputs(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for tag in re.findall(r"<input\b[^>]*>", text or "", re.I | re.S):
        attrs = {}
        for match in re.finditer(
            r"([\w:-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')",
            tag,
        ):
            attrs[match.group(1).lower()] = html.unescape(
                match.group(2) if match.group(2) is not None else match.group(3)
            )
        for key in ("id", "name"):
            attr = attrs.get(key)
            if attr:
                values[attr] = attrs.get("value", "")
    return values


def decode_json_or_jsonp(text: str):
    cleaned = (text or "").strip().lstrip("\ufeff")
    if not cleaned:
        return None
    try:
        return json.loads(cleaned)
    except ValueError:
        pass
    match = re.match(r"^[\w$.]+\s*\((.*)\)\s*;?\s*$", cleaned, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except ValueError:
        return None


def parse_services(payload) -> list[tuple[str, str]]:
    if not isinstance(payload, dict):
        return []
    service_json = payload.get("serviceJson")
    if isinstance(service_json, str):
        try:
            payload = json.loads(service_json)
        except ValueError:
            payload = None
    if isinstance(payload, dict):
        for key in ("services", "serviceList", "list"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        return []
    result = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        value = str(
            item.get("serviceName")
            or item.get("value")
            or item.get("service")
            or ""
        ).strip()
        label = str(
            item.get("serviceShowName")
            or item.get("name")
            or item.get("label")
            or value
        ).strip()
        if value:
            result.append((label, value))
    return result


def parse_services_text(text: str) -> list[tuple[str, str]]:
    parsed = parse_services(decode_json_or_jsonp(text))
    if parsed:
        return parsed

    # 锐捷部分版本返回类似：
    # student_mobile@student_telecom@student_unicom
    # 前端会把每个值同时作为 serviceName 和 serviceShowName。
    cleaned = (text or "").strip().strip('"')
    if not cleaned or cleaned.lower() in ("null", "undefined", "false", "{}", "[]"):
        return []
    if "<html" in cleaned.lower() or "<script" in cleaned.lower():
        return []
    if "@%%username@%%" in cleaned:
        cleaned = cleaned.split("@%%username@%%", 1)[1]
    result = []
    for value in cleaned.split("@"):
        value = value.strip()
        if value and re.fullmatch(r"[\w.\[\]()\-\u4e00-\u9fff]+", value):
            result.append((value, value))
    return result


def discover_services(
    session: Session,
    origin: str,
    query: str,
    username: str,
) -> list[tuple[str, str]]:
    services: list[tuple[str, str]] = []

    endpoint = origin + "/eportal/userV2.do?method=getServices"
    body = urllib.parse.urlencode(
        {"username": username, "search": "?" + query}
    ).encode("utf-8")
    try:
        response = session.request(
            endpoint,
            method="POST",
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Referer": origin + "/eportal/",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        services.extend(parse_services_text(response.text))
    except LoginError:
        pass

    endpoint = (
        origin
        + "/eportal/InterFace.do?method=getServices&queryString="
        + query
    )
    try:
        response = session.request(
            endpoint,
            method="POST",
            data=b"",
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Referer": origin + "/eportal/",
            },
        )
        services.extend(parse_services_text(response.text))
    except LoginError:
        pass

    unique: list[tuple[str, str]] = []
    seen = set()
    for label, value in services:
        key = (label, value)
        if key not in seen:
            seen.add(key)
            unique.append(key)
    return unique


def choose_service(
    services: list[tuple[str, str]],
    settings: dict,
    override: str = "",
) -> str:
    selected = (override or str(settings.get("service", "auto"))).strip()
    if selected.lower() not in ("", "auto"):
        for label, value in services:
            if selected in (label, value):
                return value
        return selected
    keyword = str(settings.get("service_keyword", "移动")).strip()
    for label, value in services:
        if keyword and (keyword in label or keyword.lower() in value.lower()):
            return value
    if len(services) == 1:
        return services[0][1]
    return "[-1-1]系统默认服务[-1-1]"


def follow_get(
    session: Session,
    url: str,
    headers: dict[str, str] | None = None,
    limit: int = 6,
    stop_external: bool = False,
    stop_host: str = "",
) -> WebResponse:
    """按浏览器行为跟随登录页 GET 跳转。"""
    current = url
    response = None
    allowed_host = (urllib.parse.urlsplit(url).hostname or "").lower()
    trusted_school_flow = is_trusted_school_host(allowed_host)
    visited = []
    for _ in range(limit):
        parts = urllib.parse.urlsplit(current)
        visited.append(f"{parts.hostname or ''}{parts.path}")
        response = session.request(current, headers=headers)
        if stop_host and (parts.hostname or "").lower() == stop_host.lower():
            return response
        if response.status not in (301, 302, 303, 307, 308) or not response.location:
            return response
        current = urllib.parse.urljoin(current, html.unescape(response.location))
        next_parts = urllib.parse.urlsplit(current)
        next_host = (next_parts.hostname or "").lower()
        if trusted_school_flow and is_trusted_school_host(next_host):
            pass
        elif next_host != allowed_host:
            if trusted_school_flow and stop_external:
                return response
            raise LoginError(
                "登录页跳转到了意外的主机，已停止访问："
                + next_host
            )
        if allowed_host == PORTAL_HOST:
            current = urllib.parse.urlunsplit(
                ("http", next_parts.netloc, next_parts.path, next_parts.query, "")
            )
    if response is None:
        raise LoginError("登录页请求没有响应")
    raise LoginError("登录页跳转次数过多：" + " -> ".join(visited))


def js_encode_component(value: str) -> str:
    return urllib.parse.quote(value, safe="-_.!~*'()")


def js_double_encode(value: str) -> str:
    return js_encode_component(js_encode_component(value))


def rsa_encrypt_shapiro(text: str, modulus_hex: str, exponent_hex: str) -> str:
    try:
        modulus = int(modulus_hex.strip(), 16)
        exponent = int(exponent_hex.strip(), 16)
    except ValueError as exc:
        raise LoginError("门户返回的 RSA 公钥格式无效") from exc
    if modulus <= 1 or exponent <= 1:
        raise LoginError("门户返回的 RSA 公钥为空")
    high_index = (modulus.bit_length() + 15) // 16 - 1
    while high_index > 0 and ((modulus >> (16 * high_index)) & 0xFFFF) == 0:
        high_index -= 1
    chunk_size = 2 * high_index
    if chunk_size <= 0:
        raise LoginError("门户 RSA 模数过小")
    try:
        raw = text.encode("latin-1")
    except UnicodeEncodeError as exc:
        raise LoginError("密码包含门户 RSA 函数不支持的字符，请先在网页确认密码格式") from exc
    raw += b"\x00" * (-len(raw) % chunk_size)
    encrypted = []
    for offset in range(0, len(raw), chunk_size):
        number = int.from_bytes(raw[offset : offset + chunk_size], "little")
        value = format(pow(number, exponent, modulus), "x")
        value = value.rjust((len(value) + 3) // 4 * 4, "0")
        encrypted.append(value)
    return " ".join(encrypted)


def _der_read_tlv(data: bytes, offset: int) -> tuple[int, bytes, int]:
    if offset + 2 > len(data):
        raise ValueError("DER 数据不完整")
    tag = data[offset]
    offset += 1
    first = data[offset]
    offset += 1
    if first & 0x80:
        count = first & 0x7F
        if count == 0 or offset + count > len(data):
            raise ValueError("DER 长度无效")
        length = int.from_bytes(data[offset : offset + count], "big")
        offset += count
    else:
        length = first
    end = offset + length
    if end > len(data):
        raise ValueError("DER 内容越界")
    return tag, data[offset:end], end


def parse_rsa_public_key(public_key_b64: str) -> tuple[int, int]:
    der = base64.b64decode(public_key_b64)
    tag, outer, end = _der_read_tlv(der, 0)
    if tag != 0x30 or end != len(der):
        raise LoginError("统一认证 RSA 公钥外层格式无效")
    tag, algorithm, offset = _der_read_tlv(outer, 0)
    if tag != 0x30:
        raise LoginError("统一认证 RSA 公钥算法字段无效")
    tag, bit_string, offset = _der_read_tlv(outer, offset)
    if tag != 0x03 or not bit_string or bit_string[0] != 0:
        raise LoginError("统一认证 RSA 公钥 BIT STRING 无效")
    inner = bit_string[1:]
    tag, rsa_seq, _ = _der_read_tlv(inner, 0)
    if tag != 0x30:
        raise LoginError("统一认证 RSA 公钥内层格式无效")
    tag, modulus_bytes, offset = _der_read_tlv(rsa_seq, 0)
    if tag != 0x02:
        raise LoginError("统一认证 RSA 模数字段无效")
    tag, exponent_bytes, _ = _der_read_tlv(rsa_seq, offset)
    if tag != 0x02:
        raise LoginError("统一认证 RSA 指数字段无效")
    return int.from_bytes(modulus_bytes, "big"), int.from_bytes(exponent_bytes, "big")


def rsa_encrypt_jsencrypt(text: str, public_key_b64: str) -> str:
    modulus, exponent = parse_rsa_public_key(public_key_b64)
    key_length = (modulus.bit_length() + 7) // 8
    message = text.encode("utf-8")
    if len(message) > key_length - 11:
        raise LoginError("密码过长，无法使用统一认证 RSA 公钥加密")
    padding_length = key_length - len(message) - 3
    padding = bytes(secrets.randbelow(255) + 1 for _ in range(padding_length))
    block = b"\x00\x02" + padding + b"\x00" + message
    encrypted = pow(int.from_bytes(block, "big"), exponent, modulus)
    return base64.b64encode(encrypted.to_bytes(key_length, "big")).decode("ascii")


def sso_secret_param(password: str, public_key_b64: str = SSO_PUBLIC_KEY) -> str:
    if not password:
        return ""
    chunks = [
        rsa_encrypt_jsencrypt(password[index : index + 30], public_key_b64)
        for index in range(0, len(password), 30)
    ]
    # 浏览器先 encodeURI 单个密文（Base64 不需要变化），再对 JSON 数组做
    # encodeURIComponent。最终作为 JSON 字符串发送。
    return urllib.parse.quote(
        json.dumps(chunks, ensure_ascii=False, separators=(",", ":")),
        safe="",
    )


def is_trusted_school_host(host: str) -> bool:
    host = (host or "").lower()
    return host == PORTAL_HOST or host == "cqut.edu.cn" or host.endswith(".cqut.edu.cn")


def parse_sso_public_key(text: str) -> str:
    start = (text or "").find("BEGIN PUBLIC KEY")
    if start < 0:
        return ""
    chunk = text[start : start + 2000]
    pieces = re.findall(r"['\"]([A-Za-z0-9+/=]{20,})['\"]", chunk)
    return "".join(piece for piece in pieces if "PUBLIC" not in piece and "END" not in piece)


def sso_login(
    session: Session,
    sso_entry_url: str,
    page_text: str,
    username: str,
    password: str,
    logger: Logger,
    settings: dict,
) -> bool:
    public_key = parse_sso_public_key(page_text) or SSO_PUBLIC_KEY
    payload = {
        "name": username,
        "pwd": sso_secret_param(password, public_key),
        "verifyCode": None,
        "universityId": SSO_UNIVERSITY_ID,
        "loginType": "login",
    }
    entry_parts = urllib.parse.urlsplit(sso_entry_url)
    entry_host = (entry_parts.hostname or "").lower()
    if entry_host.startswith("sid."):
        sid_origin = f"{entry_parts.scheme}://{entry_parts.netloc}"
        delegated_login_url = (
            sid_origin
            + "/cas/clientredirect?client_name=adapter&service="
            + urllib.parse.quote(sso_entry_url, safe="")
        )
        logger.write("创建统一身份认证会话")
        sso_page = follow_get(session, delegated_login_url, limit=12)
        uis_login_url = sso_page.url
    else:
        uis_login_url = sso_entry_url
    logger.write("使用重庆理工大学统一身份认证登录")
    response = session.request(
        SSO_LOGIN_ENDPOINT,
        method="POST",
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
        },
    )
    result = decode_json_or_jsonp(response.text)
    if not isinstance(result, dict):
        raise LoginError(f"统一认证返回了无法识别的响应（HTTP {response.status}）")
    code = str(result.get("code", ""))
    message = str(result.get("msg") or result.get("message") or "")
    if code == "200":
        logger.write("统一身份认证通过，正在返回校园网门户")
        portal_response = follow_get(
            session,
            uis_login_url,
            limit=15,
            stop_external=True,
        )
        logger.write(f"SSO 回跳完成：HTTP {portal_response.status}")
        deadline = time.monotonic() + max(
            5,
            int(settings.get("post_login_wait_seconds", 240)),
        )
        verification_session = Session(
            min(4.0, float(settings.get("request_timeout", 8)))
        )
        logger.write("等待校园网门户同步联网状态")
        while time.monotonic() < deadline:
            if check_online(verification_session)[0]:
                logger.write("认证成功，外网已经连通", "OK")
                return True
            time.sleep(2)
        raise PendingReleaseError("统一身份认证已通过，但校园网门户仍未完成放行")
    safe_message = redact(message, username, password, "")
    if code == "16300":
        raise LoginError("学校要求二次验证，当前脚本无法自动完成")
    if code == "601":
        raise LoginError("该账号存在多个身份，需要在统一认证页面先选择身份")
    if any(
        word in message
        for word in ("密码", "账号", "用户不存在", "用户信息不存在", "用户名")
    ):
        raise CredentialError(
            "统一身份认证拒绝了账号或密码"
            + (f"：{safe_message}" if safe_message else "")
        )
    raise LoginError(
        f"统一身份认证失败（code={code}）"
        + (f"：{safe_message}" if safe_message else "")
    )


def wait_for_online(
    settings: dict,
    logger: Logger,
    seconds: float | None = None,
) -> bool:
    wait_seconds = int(settings.get("post_login_wait_seconds", 240))
    if seconds is not None:
        wait_seconds = int(seconds)
    deadline = time.monotonic() + max(5, wait_seconds)
    verification_session = Session(
        min(4.0, float(settings.get("request_timeout", 8)))
    )
    logger.write("等待校园网门户同步联网状态")
    while time.monotonic() < deadline:
        if check_online(verification_session)[0]:
            logger.write("认证成功，外网已经连通", "OK")
            return True
        time.sleep(2)
    return False


def edge_sso_login(
    page_url: str,
    username: str,
    password: str,
    logger: Logger,
) -> str:
    node = shutil.which("node")
    helper = Path(__file__).with_name("edge_sso_login.mjs")
    if not node or not helper.exists():
        logger.write("未找到 Node.js 或 Edge 登录助手，尝试直接 SSO", "WARN")
        return EDGE_UNAVAILABLE
    payload = json.dumps(
        {
            "url": page_url,
            "username": username,
            "password": password,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    logger.write("启动无界面 Edge 完成学校 SSO 登录")
    child_env = os.environ.copy()
    child_env.pop("CQUT_USERNAME", None)
    child_env.pop("CQUT_PASSWORD", None)
    try:
        completed = subprocess.run(
            [node, str(helper)],
            input=payload,
            capture_output=True,
            timeout=150,
            env=child_env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.write(f"Edge 登录助手启动失败：{exc}", "WARN")
        return EDGE_UNAVAILABLE
    lines = [
        line.strip()
        for line in completed.stdout.decode("utf-8", "replace").splitlines()
        if line.strip()
    ]
    if not lines:
        logger.write("Edge 登录助手没有返回结果", "WARN")
        return EDGE_UNAVAILABLE
    try:
        result = json.loads(lines[-1])
    except ValueError:
        logger.write("Edge 登录助手返回了无法识别的结果", "WARN")
        return EDGE_UNAVAILABLE
    result_url = str(result.get("url") or "")
    if result_url:
        parts = urllib.parse.urlsplit(result_url)
        target = (parts.hostname or "") + (parts.path or "")
    else:
        target = "(unknown)"
    logger.write(f"Edge 登录阶段：{result.get('stage', 'unknown')}，页面：{target}")
    for request in result.get("requests", [])[-12:]:
        logger.write(f"浏览器页面请求：{request}")
    if result.get("ok"):
        logger.write("Edge 已完成统一身份认证提交")
        if result.get("stage") == "success":
            return EDGE_SUCCESS
        return EDGE_SUBMITTED
    message = redact(
        str(result.get("error") or result.get("reason") or "SSO 登录失败"),
        username,
        password,
        "",
    )
    if any(word in message for word in ("密码", "账号", "用户信息不存在")):
        raise CredentialError("统一身份认证拒绝了账号或密码：" + message)
    if str(result.get("stage") or "") == "form-not-found":
        logger.write("Edge 已打开门户，但门户没有返回登录表单", "WARN")
        return EDGE_NO_FORM
    logger.write("Edge SSO 登录未完成：" + message, "WARN")
    return EDGE_UNAVAILABLE


def decode_png_rgb(data: bytes) -> tuple[int, int, list[bytes]]:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise LoginError("验证码不是 PNG 图片")
    position = 8
    compressed = []
    palette = b""
    width = height = bit_depth = color_type = 0
    while position + 12 <= len(data):
        length = struct.unpack(">I", data[position : position + 4])[0]
        chunk_type = data[position + 4 : position + 8]
        chunk = data[position + 8 : position + 8 + length]
        position += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _, _, _ = struct.unpack(
                ">IIBBBBB", chunk
            )
        elif chunk_type == b"PLTE":
            palette = chunk
        elif chunk_type == b"IDAT":
            compressed.append(chunk)
        elif chunk_type == b"IEND":
            break
    if bit_depth != 8 or color_type not in (0, 2, 3, 6):
        raise LoginError(
            f"暂不支持验证码 PNG 格式：bit_depth={bit_depth}, color_type={color_type}"
        )
    channels = {0: 1, 2: 3, 3: 1, 6: 4}[color_type]
    stride = width * channels
    raw = zlib.decompress(b"".join(compressed))
    rows: list[bytes] = []
    previous = bytearray(stride)
    offset = 0
    for _ in range(height):
        filter_type = raw[offset]
        offset += 1
        current = bytearray(raw[offset : offset + stride])
        offset += stride
        for index in range(stride):
            left = current[index - channels] if index >= channels else 0
            above = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 1:
                current[index] = (current[index] + left) & 0xFF
            elif filter_type == 2:
                current[index] = (current[index] + above) & 0xFF
            elif filter_type == 3:
                current[index] = (current[index] + ((left + above) // 2)) & 0xFF
            elif filter_type == 4:
                estimate = left + above - upper_left
                pa = abs(estimate - left)
                pb = abs(estimate - above)
                pc = abs(estimate - upper_left)
                predictor = left if pa <= pb and pa <= pc else (
                    above if pb <= pc else upper_left
                )
                current[index] = (current[index] + predictor) & 0xFF
            elif filter_type != 0:
                raise LoginError(f"验证码 PNG 使用了未知过滤器 {filter_type}")
        rows.append(bytes(current))
        previous = current

    rgb_rows = []
    for row in rows:
        rgb = bytearray()
        for x in range(width):
            offset = x * channels
            if color_type == 0:
                rgb.extend((row[offset],) * 3)
            elif color_type == 2:
                rgb.extend(row[offset : offset + 3])
            elif color_type == 6:
                rgb.extend(row[offset : offset + 3])
            else:
                index = row[offset] * 3
                if index + 3 <= len(palette):
                    rgb.extend(palette[index : index + 3])
                else:
                    rgb.extend((0, 0, 0))
        rgb_rows.append(bytes(rgb))
    return width, height, rgb_rows


def recognize_captcha(data: bytes, interactive: bool = False) -> str:
    width, height, rows = decode_png_rgb(data)
    active_columns = [
        x
        for x in range(width)
        if any(min(rows[y][x * 3 : x * 3 + 3]) < 220 for y in range(height))
    ]
    spans: list[list[int]] = []
    for x in active_columns:
        if not spans or x > spans[-1][1] + 1:
            spans.append([x, x])
        else:
            spans[-1][1] = x
    if len(spans) != 4:
        ascii_preview = "\n".join(
            "".join(
                "#" if min(row[x * 3 : x * 3 + 3]) < 180 else "."
                for x in range(width)
            )
            for row in rows
        )
        if interactive:
            print(ascii_preview)
            entered = input("未能自动分段，请输入图中 4 位验证码：").strip()
            if re.fullmatch(r"\d{4}", entered):
                return entered
        raise LoginError(f"验证码自动分段失败，检测到 {len(spans)} 个字形")

    digits = []
    for x0, x1 in spans:
        active_rows = [
            y
            for y in range(height)
            if any(min(rows[y][x * 3 : x * 3 + 3]) < 220 for x in range(x0, x1 + 1))
        ]
        y0, y1 = min(active_rows), max(active_rows)
        bitmap = "\n".join(
            "".join(
                "1" if min(rows[y][x * 3 : x * 3 + 3]) < 180 else "0"
                for x in range(x0, x1 + 1)
            )
            for y in range(y0, y1 + 1)
        )
        digit = CAPTCHA_TEMPLATES.get(hashlib.sha256(bitmap.encode("ascii")).hexdigest())
        if not digit:
            if interactive:
                print(bitmap.replace("0", ".").replace("1", "#"))
                entered = input("出现未收录字形，请输入这张验证码的 4 位数字：").strip()
                if re.fullmatch(r"\d{4}", entered):
                    return entered
            raise LoginError("验证码出现了未收录的字形；可能门户更新了验证码字体")
        digits.append(digit)
    return "".join(digits)


def parse_login_page(text: str) -> dict[str, str]:
    inputs = parse_inputs(text)
    inputs["passwordEncrypt"] = inputs.get("passwordEncrypt", "false")
    return inputs


def build_login_body(
    username: str,
    password: str,
    service: str,
    query: str,
    captcha: str,
    password_encrypted: bool,
) -> bytes:
    fields = {
        "userId": username,
        "password": password,
        "service": service,
        "queryString": query,
        "operatorPwd": "",
        "operatorUserId": "",
        "validcode": captcha,
        "passwordEncrypt": "true" if password_encrypted else "false",
    }
    return "&".join(
        key + "=" + js_double_encode(value) for key, value in fields.items()
    ).encode("ascii")


def classify_login_message(message: str) -> str:
    lowered = message.lower()
    if any(word in message for word in ("验证码", "校验码")) or "validcode" in lowered:
        return "captcha"
    if any(word in message for word in ("密码", "账号不存在", "用户不存在", "用户名")):
        return "credentials"
    if any(word in message for word in ("服务", "出口", "运营商")):
        return "service"
    return "other"


def redact(message: str, username: str, password: str, captcha: str) -> str:
    result = message or ""
    secrets_to_hide = sorted(
        (value for value in (password, username, captcha) if value),
        key=len,
        reverse=True,
    )
    for secret in secrets_to_hide:
        if secret:
            result = result.replace(secret, "***")
    return result


def login_once(
    session: Session,
    settings: dict,
    username: str,
    password: str,
    logger: Logger,
    service_override: str = "",
    interactive: bool = True,
) -> bool:
    online, portal_hint = check_online(session)
    if online:
        logger.write("当前已经联网，无需重复认证", "OK")
        return True

    location, query = find_portal_location(session, settings)
    origin = normalize_origin(location)
    origin_host = (urllib.parse.urlsplit(origin).hostname or "").lower()
    if not is_trusted_school_host(origin_host):
        raise LoginError(
            "校园网门户跳转到了未授权主机，已停止提交凭据："
            + (origin_host or "(unknown)")
        )
    logger.write(f"发现校园网门户：{origin}")
    logger.write("已取得 AC 下发的登录参数")

    page_url = login_page_url(location, query)
    # AC 下发的登录地址和会话可能只能用一次。必须先交给独立的浏览器会话，
    # 不能让 Python 先打开一遍再交给浏览器。
    if os.name == "nt":
        edge_result = edge_sso_login(page_url, username, password, logger)
        if edge_result in (EDGE_SUCCESS, EDGE_SUBMITTED):
            if wait_for_online(settings, logger):
                return True
            raise PendingReleaseError(
                "统一身份认证已提交，但校园网门户尚未放行；先等待，不重复提交"
            )
        if edge_result == EDGE_NO_FORM:
            # 门户不再给出登录表单，通常说明这台设备已有认证会话正在放行。
            # 这时换另一条通道再登录会制造冲突会话，所以只观察、不重提。
            logger.write("门户未返回登录表单，先等待现有会话放行", "WARN")
            if wait_for_online(settings, logger):
                return True
            raise PendingReleaseError(
                "门户未返回登录表单，且外网仍未放行；先等待，不重复提交"
            )
        logger.write("浏览器登录未完成，尝试直接 SSO 接口", "WARN")

    page = follow_get(
        session,
        page_url,
        headers={
            "Referer": portal_hint or origin + "/",
            "Accept": "text/html,application/xhtml+xml",
        },
        limit=15,
        stop_host="sid.cqut.edu.cn",
    )
    final_query = extract_query_string(page.url)
    if final_query and "wlanuserip" in final_query.lower():
        location = page.url
        query = final_query
        origin = normalize_origin(page.url)
    page_text = page.text
    page_host = (urllib.parse.urlsplit(page.url).hostname or "").lower()
    if page_host.endswith(".cqut.edu.cn") or page_host == "cqut.edu.cn":
        return sso_login(
            session,
            page.url,
            page_text,
            username,
            password,
            logger,
            settings,
        )
    if "设备未注册" in page_text:
        raise LoginError(
            "门户返回“设备未注册”。登录参数可能已过期，请稍后重试。"
        )
    inputs = parse_login_page(page_text)
    encrypt_flag = str(inputs.get("passwordEncrypt", "false")).lower() == "true"
    if encrypt_flag and not inputs.get("publicKeyModulus"):
        raise LoginError("门户要求 RSA 加密，但登录页没有返回公钥")

    services = discover_services(session, origin, query, username)
    service = choose_service(services, settings, service_override)
    if services:
        shown = "、".join(label for label, _ in services[:8])
        logger.write(f"可用服务：{shown}")
    if service:
        logger.write(f"本次使用服务：{service}")
    else:
        logger.write("未识别到服务出口，将按门户默认值提交", "WARN")

    max_attempts = max(1, int(settings.get("max_captcha_attempts", 6)))
    for attempt in range(1, max_attempts + 1):
        captcha_url = (
            origin
            + "/eportal/validcode?r="
            + str(random.randint(100000, 9999999))
        )
        captcha_response = session.request(
            captcha_url,
            headers={
                "Referer": page_url,
                "Accept": "image/avif,image/webp,image/png,image/*,*/*;q=0.8",
            },
        )
        if captcha_response.status != 200:
            raise LoginError(f"验证码获取失败：HTTP {captcha_response.status}")
        captcha = recognize_captcha(captcha_response.body, interactive=interactive)
        logger.write(f"验证码识别完成（第 {attempt}/{max_attempts} 次）")

        encrypted = encrypt_flag
        submitted_password = password
        if encrypted:
            query_values = urllib.parse.parse_qs(query)
            mac = (query_values.get("mac") or ["111111111"])[0]
            if len(submitted_password) < 150:
                submitted_password += ">" + mac
            submitted_password = rsa_encrypt_shapiro(
                submitted_password[::-1],
                inputs.get("publicKeyModulus", ""),
                inputs.get("publicKeyExponent", "10001"),
            )

        body = build_login_body(
            username,
            submitted_password,
            service,
            query,
            captcha,
            encrypted,
        )
        response = session.request(
            origin + "/eportal/InterFace.do?method=login",
            method="POST",
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Referer": page_url,
                "Origin": origin,
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        result = decode_json_or_jsonp(response.text)
        if isinstance(result, dict):
            status = str(result.get("result", "")).lower()
            message = str(result.get("message") or result.get("msg") or "")
        else:
            status = ""
            message = ""
        if status in ("success", "ok", "1", "true"):
            time.sleep(1)
            verified, _ = check_online(session)
            if verified:
                logger.write("认证成功，外网已经连通", "OK")
                return True
            raise LoginError("门户提示成功，但外网验证未通过；可能服务出口不正确")

        kind = classify_login_message(message)
        safe_message = redact(message, username, password, captcha)
        logger.write(
            f"认证未成功：{safe_message or ('HTTP ' + str(response.status))}",
            "WARN",
        )
        if kind == "credentials":
            raise CredentialError("账号或密码被门户拒绝，已停止自动重试以避免锁号")
        if kind != "captcha" and attempt >= 2:
            break
        if attempt < max_attempts:
            time.sleep(0.5)

    raise LoginError("认证失败。请先在浏览器手动登录一次，然后运行 --diagnose 查看诊断信息")


def diagnose(settings: dict, logger: Logger) -> int:
    session = Session(float(settings.get("request_timeout", 8)))
    online, portal_hint = check_online(session)
    if online:
        logger.write("网络状态：已联网", "OK")
        if portal_hint:
            logger.write(f"门户跳转：{normalize_origin(portal_hint)}")
        print("当前已经在线。要检查登录页，请先让认证过期，或换到尚未认证的校园网连接。")
        return 0
    logger.write("网络状态：未认证或未联网", "WARN")
    try:
        location, query = find_portal_location(session, settings)
    except LoginError as exc:
        logger.write(str(exc), "ERROR")
        return 1
    origin = normalize_origin(location)
    logger.write(f"门户地址：{origin}")
    logger.write(f"登录参数：{', '.join(sorted(urllib.parse.parse_qs(query)))}")
    page_url = login_page_url(location, query)
    response = follow_get(
        session,
        page_url,
        limit=15,
        stop_host="sid.cqut.edu.cn",
    )
    final_query = extract_query_string(response.url)
    if final_query and "wlanuserip" in final_query.lower():
        location = response.url
        query = final_query
        page_url = response.url
        origin = normalize_origin(response.url)
    page_host = (urllib.parse.urlsplit(response.url).hostname or "").lower()
    if page_host.endswith(".cqut.edu.cn") or page_host == "cqut.edu.cn":
        logger.write("认证方式：学校统一身份认证（SSO）")
        logger.write(f"SSO 页面：{page_host}")
        logger.write(f"登录页响应：HTTP {response.status}")
        logger.write("RSA 公钥：已内置，可正常加载")
        return 0
    inputs = parse_login_page(response.text)
    logger.write(
        "密码 RSA 加密："
        + ("开启" if str(inputs.get("passwordEncrypt", "false")).lower() == "true" else "关闭")
    )
    logger.write(f"登录页响应：HTTP {response.status}")
    credentials = None
    try:
        credentials = load_credentials()
    except LoginError:
        pass
    if credentials:
        services = discover_services(session, origin, query, credentials[0])
        for label, value in services:
            logger.write(f"服务：{label} => {value}")
    captcha_response = session.request(
        origin + f"/eportal/validcode?r={random.randint(100000, 9999999)}",
        headers={"Referer": page_url},
    )
    try:
        code = recognize_captcha(captcha_response.body, interactive=True)
        logger.write("验证码识别：成功", "OK")
    except LoginError as exc:
        logger.write(str(exc), "ERROR")
        return 1
    return 0


def watch(
    settings: dict,
    username: str,
    password: str,
    logger: Logger,
    service_override: str,
) -> None:
    start = time.monotonic()
    warmup = max(0, int(settings.get("warmup_seconds", 180)))
    interval = max(20, int(settings.get("check_interval", 60)))
    logger.write(f"守护模式已启动，正常联网时每 {interval} 秒检查一次")
    while True:
        session = Session(float(settings.get("request_timeout", 8)))
        try:
            login_once(
                session,
                settings,
                username,
                password,
                logger,
                service_override=service_override,
                interactive=False,
            )
            delay = interval
        except KeyboardInterrupt:
            raise
        except CredentialError:
            logger.write(
                "守护模式已停止：账号或密码被拒绝。请核对密码后重新启动。",
                "ERROR",
            )
            return
        except PendingReleaseError as exc:
            # 认证已经提交过，门户只是还没放行。此时再开新会话会互相冲突，
            # 所以只轮询联网状态，等放行窗口过去后才允许重新提交。
            logger.write(str(exc), "WARN")
            logger.write("门户可能仍在放行中，暂停重复提交，仅轮询联网状态")
            if wait_for_online(settings, logger, seconds=max(60, interval * 2)):
                delay = interval
            else:
                delay = max(interval, 120)
        except LoginError as exc:
            logger.write(str(exc), "WARN")
            warmup_left = warmup - (time.monotonic() - start)
            delay = 15 if warmup_left > 0 else 60
        except Exception as exc:
            logger.write(f"未预期错误：{exc}", "ERROR")
            delay = 60
        try:
            time.sleep(delay)
        except KeyboardInterrupt:
            return


def build_startup_vbs(executable: Path, script: Path) -> str:
    def escape(value: Path) -> str:
        return str(value).replace('"', '""')

    return (
        'Set shell = CreateObject("WScript.Shell")\r\n'
        "q = Chr(34)\r\n"
        f'cmd = q & "{escape(executable)}" & q & " " & q & '
        f'"{escape(script)}" & q & " --watch --quiet"\r\n'
        "shell.Run cmd, 0, False\r\n"
    )


def remove_fallback_autostart() -> bool:
    """删除启动文件夹与 HKCU Run 中的旧版自启项。"""
    removed = False
    startup_file = startup_vbs_path()
    if startup_file and startup_file.exists():
        startup_file.unlink()
        removed = True

    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            key_path,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            try:
                winreg.DeleteValue(key, TASK_NAME)
                removed = True
            except FileNotFoundError:
                pass
    except FileNotFoundError:
        pass
    return removed


def install_task() -> None:
    if os.name != "nt":
        raise LoginError("开机自启只支持 Windows")
    python_exe = Path(sys.executable)
    pythonw = python_exe.with_name("pythonw.exe")
    executable = pythonw if pythonw.exists() else python_exe
    script = Path(__file__).resolve()
    run_command = (
        subprocess.list2cmdline([str(executable), str(script), "--watch", "--quiet"])
    )
    command = [
        "schtasks.exe",
        "/Create",
        "/TN",
        TASK_NAME,
        "/SC",
        "ONLOGON",
        "/RL",
        "LIMITED",
        "/TR",
        run_command,
        "/F",
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="gb18030",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode == 0:
        print(f'已安装开机自启计划任务：{TASK_NAME}')
        try:
            if remove_fallback_autostart():
                print("已清理旧的启动文件夹或注册表自启项，避免重复运行。")
        except OSError as exc:
            print(f"警告：计划任务已安装，但旧自启项清理失败：{exc}")
        return

    # 部分学校的 Windows 策略禁止普通用户创建登录触发的计划任务，
    # 也可能忽略 HKCU Run。启动文件夹中的隐藏 VBS 更稳定，也不需要管理员权限。
    startup_file = startup_vbs_path()
    if startup_file is None:
        raise LoginError("无法定位当前用户的 Windows 启动文件夹")
    try:
        startup_file.parent.mkdir(parents=True, exist_ok=True)
        content = build_startup_vbs(executable, script)
        startup_file.write_bytes(b"\xff\xfe" + content.encode("utf-16le"))

        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            key_path,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            try:
                winreg.DeleteValue(key, TASK_NAME)
            except FileNotFoundError:
                pass
    except (OSError, ImportError) as exc:
        task_error = completed.stderr.strip() or completed.stdout.strip()
        raise LoginError(
            "计划任务和启动文件夹自启项都无法创建。"
            f"计划任务：{task_error or '拒绝访问'}；启动文件夹：{exc}"
        ) from exc
    print(
        "Windows 计划任务被系统策略拒绝，已改用当前用户启动文件夹。"
        "下次登录 Windows 时会自动开始运行。"
    )


def uninstall_task() -> None:
    if os.name != "nt":
        raise LoginError("开机自启只支持 Windows")
    removed = False
    completed = subprocess.run(
        ["schtasks.exe", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True,
        text=True,
        encoding="gb18030",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode == 0:
        removed = True
    try:
        removed = remove_fallback_autostart() or removed
    except OSError as exc:
        raise LoginError(f"删除当前用户启动项失败：{exc}") from exc
    if not removed:
        raise LoginError("没有找到重庆理工大学校园网开机自启项")
    print(f'已删除开机自启：{TASK_NAME}')


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="重庆理工大学锐捷 ePortal 自动认证（有线/无线）"
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--init", action="store_true", help="保存账号密码")
    action.add_argument("--check", action="store_true", help="只检查联网状态")
    action.add_argument("--diagnose", action="store_true", help="检查门户和验证码")
    action.add_argument("--watch", action="store_true", help="持续监测并自动重连")
    action.add_argument(
        "--paths",
        action="store_true",
        help="显示配置、日志和开机自启文件位置",
    )
    action.add_argument(
        "--install-task",
        "--install-autostart",
        action="store_true",
        help="安装开机自启（计划任务被拒绝时使用当前用户启动项）",
    )
    action.add_argument(
        "--uninstall-task",
        "--uninstall-autostart",
        action="store_true",
        help="删除开机自启",
    )
    action.add_argument(
        "--recognize-image",
        metavar="PNG",
        help="离线识别一张门户验证码图片",
    )
    parser.add_argument(
        "--service",
        default="",
        help="临时指定服务出口，例如“移动”；留空自动选择",
    )
    parser.add_argument("--quiet", action="store_true", help="只输出警告和错误")
    return parser


def print_paths() -> None:
    startup = startup_vbs_path()
    items = (
        ("数据目录", data_dir()),
        ("配置文件", SETTINGS_PATH),
        ("凭据文件", CREDENTIALS_PATH),
        ("日志文件", LOG_PATH),
        ("开机启动文件", startup or Path("(当前系统不支持)")),
    )
    for label, path in items:
        print(f"{label}：{path}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logger = Logger(quiet=args.quiet)
    try:
        if args.recognize_image:
            data = Path(args.recognize_image).read_bytes()
            print(recognize_captcha(data, interactive=True))
            return 0
        if args.paths:
            print_paths()
            return 0
        settings = load_settings()
        if args.install_task:
            install_task()
            return 0
        if args.uninstall_task:
            uninstall_task()
            return 0
        if args.init:
            initialize(settings, logger)
            return 0
        if args.check:
            online, portal_hint = check_online(
                Session(float(settings.get("request_timeout", 8)))
            )
            if online:
                logger.write("当前已经联网", "OK")
                return 0
            logger.write("当前未联网或尚未认证", "WARN")
            if portal_hint:
                logger.write(f"检测到门户：{normalize_origin(portal_hint)}")
            return 1
        if args.diagnose:
            return diagnose(settings, logger)

        username, password = load_credentials()
        if args.watch:
            if not acquire_watch_lock():
                logger.write("守护模式已经在运行，本次不重复启动")
                return 0
            try:
                watch(settings, username, password, logger, args.service)
            finally:
                release_watch_lock()
            return 0
        session = Session(float(settings.get("request_timeout", 8)))
        return 0 if login_once(
            session,
            settings,
            username,
            password,
            logger,
            service_override=args.service,
            interactive=sys.stdin.isatty(),
        ) else 1
    except KeyboardInterrupt:
        logger.write("已停止")
        return 130
    except LoginError as exc:
        logger.write(str(exc), "ERROR")
        return 1
    except OSError as exc:
        logger.write(f"文件操作失败：{exc}", "ERROR")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
