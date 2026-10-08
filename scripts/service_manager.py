#!/usr/bin/env python3
"""
游戏助手服务管理脚本（Boss招式识别Demo）
  部署 / 健康检查 / 关闭服务（先关 BARDemo 再停服务）/ Demo 资产就绪 / 进度查询

用法:
    python service_manager.py health              # 健康检查（瞬间返回）
    python service_manager.py deploy              # 后台部署，立即返回
    python service_manager.py shutdown            # 关闭服务（先结束 BARDemo.exe 再停服务）
    python service_manager.py status              # 查询后台任务进度
    python service_manager.py ensure              # 健康检查 + 按需部署
    python service_manager.py ensure-demo         # 确保 BARDemo/ thirdparty/ 就绪（缺则下载解压）
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib import request
from urllib.error import URLError

_SCRIPT_DIR = Path(__file__).resolve().parent
_DEFAULT_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "GameAssistant"

# 本脚本的 stdout 是 agent 的解析契约（纯 JSON），日志一律走 stderr。
# 同时把两个流强制成 UTF-8，避免中文在 GBK 控制台下变成乱码。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
_LOG_DIR = _DEFAULT_DATA_DIR
_LOG_SUB_DIR = _LOG_DIR / "log"
_STATUS_FILE = _LOG_DIR / "task_status.json"

SERVICE_HOST = "127.0.0.1"
# 9190 与部分 Windows 服务冲突，新版服务端默认 22919；旧版已发布出去仍在用
# 9190 —— 运行时经 resolve_service_port() 探测（校验服务身份），显示用新默认。
SERVICE_PORT = 22919
SERVICE_PORT_LEGACY = 9190
SERVICE_URL = f"http://{SERVICE_HOST}:{SERVICE_PORT}"
DEPLOY_SCRIPT = _SCRIPT_DIR / "deploy.py"
_SKILL_ROOT = _SCRIPT_DIR.parent



def _setup_logger(name: str) -> logging.Logger:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    _LOG_SUB_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 日志轮转：跨天后第一次配置 logger 时，把旧日志改名成带日期的历史文件
    # （只保留最近一份，更早的删除）。不清空直接覆盖——跨天后的 status 轮询
    # 也会触发 setup，清空会让人以为"日志没了"。改名失败（旧文件被长任务
    # 占用）就保留原文件继续追加，混排两天内容好过丢日志。
    log_path = _LOG_SUB_DIR / "service_manager.log"
    try:
        if log_path.exists() and datetime.fromtimestamp(
            log_path.stat().st_mtime
        ).date() != datetime.now().date():
            prev_date = datetime.fromtimestamp(
                log_path.stat().st_mtime).strftime("%Y-%m-%d")
            keep = _LOG_SUB_DIR / f"service_manager.{prev_date}.log"
            keep.unlink(missing_ok=True)
            log_path.rename(keep)
    except OSError:
        pass
    # delay=True：第一条日志真正写入时才创建文件——status/health 这类
    # 只打印 JSON 的命令不应留下空文件误导排障（flush 不受影响：
    # logging 每条记录写完都会显式 flush）。
    fh = logging.FileHandler(str(log_path), mode="a", encoding="utf-8",
                             delay=True)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


log = _setup_logger("service_manager")


def _resolve_data_dir(install_dir: str) -> tuple[Path, bool]:
    """数据目录：install_dir 非空且可写→用它；否则回落默认。返回 (目录, 是否回落)。"""
    install_dir = (install_dir or "").strip()
    if not install_dir:
        return _DEFAULT_DATA_DIR, False
    p = Path(install_dir)
    if not p.is_dir():
        return _DEFAULT_DATA_DIR, True  # 不存在就回落，不要凭一个拼错的路径现造目录
    try:
        probe = p / ".write_probe"
        probe.write_text("ok")
        probe.unlink()
        return p, False
    except OSError:
        return _DEFAULT_DATA_DIR, True


def _apply_data_dir(install_dir: str) -> None:
    """将日志/状态根目录切到 install_dir（可写时）或回落默认目录。"""
    global _LOG_DIR, _LOG_SUB_DIR, _STATUS_FILE, log

    old_dir = _LOG_DIR
    _LOG_DIR, fell_back = _resolve_data_dir(install_dir)
    _LOG_SUB_DIR = _LOG_DIR / "log"
    _STATUS_FILE = _LOG_DIR / "task_status.json"
    log = _setup_logger("service_manager")

    if _LOG_DIR != old_dir:
        # 日志位置变了就明说，避免按旧路径找文件时看到"空的/不存在"
        log.info("日志/状态目录: %s", _LOG_DIR)
    if fell_back:
        msg = f"预装路径不可写，日志/状态目录已回落到默认目录: {_LOG_DIR}"
        log.warning(msg)
        print(f"[warning] {msg}", file=sys.stderr)


# ── 状态文件 ────────────────────────────────────────────────

def _read_status() -> dict:
    if not _STATUS_FILE.exists():
        return {"task": "none", "status": "idle"}
    try:
        with open(_STATUS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {"task": "none", "status": "idle"}
    except (json.JSONDecodeError, OSError):
        return {"task": "none", "status": "idle"}


def _write_status(task: str, status: str, stage: str = "",
                  progress: float = -1, detail: str = "",
                  **extra) -> None:
    payload: dict = {
        "task": task,
        "status": status,
        "stage": stage,
        "progress": max(0, min(100, progress)) if progress >= 0 else -1,
        "detail": detail,
        **extra,
    }
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _STATUS_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    # Windows 上另一个进程正在读该文件时 replace 会失败，重试几次即可
    for attempt in range(3):
        try:
            tmp.replace(_STATUS_FILE)
            return
        except OSError:
            if attempt == 2:
                raise
            time.sleep(0.2)


def _is_pid_alive(pid: int) -> bool:
    """检查进程是否存活（Windows 用）。"""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, timeout=5,
        )
        return str(pid) in result.stdout
    except Exception:
        return False


# ── 进度解析 ────────────────────────────────────────────────

# 分段标记。关键词必须挑**只有真正进入该阶段时才会打印**的原文片段：
# 像 "模型"、"下载" 这种泛化词会被配置announcement行命中（例如 deploy 启动时打的
# "--skip-models: 跳过模型下载"），把进度一上来就顶到高位，后面真实阶段反而被压住。
# 列表顺序敏感：先匹配到的赢。
_DEPLOY_PHASES = [
    ("已在运行", ("服务已在运行", 100)),
    ("部署成功", ("部署完成", 100)),
    ("[OK] 就绪", ("服务就绪", 100)),
    # —— 版本更新检测（关键词与 deploy.py 日志原文精确对应，措辞勿改）。
    # pct 必须随执行顺序单调（status 对整份日志取最大值）：
    # 8 检测 → 10 等用户确认（更新/安装方式弹窗，可能停很久）→ 12 下载更新包
    # →（20 下载服务包 / 45 解压 / 60 模型）→ 80 应用更新 → 90 启动 → 100 就绪
    ("检测服务端与模型更新", ("检测更新", 8)),
    ("等待用户确认", ("等待用户确认", 10)),
    ("下载更新包", ("下载更新", 12)),
    ("应用更新", ("应用更新", 80)),
    ("模型下载完成", ("模型下载完成", 85)),
    ("安装到目标目录", ("安装模型", 80)),
    ("下载 AI 模型", ("下载 AI 模型", 60)),
    ("解压", ("安装服务包", 45)),
    ("下载: http", ("下载服务包", 20)),
    # 手动模式下弹窗等用户选包，可能停留很久，必须能显示出来
    ("等待用户选择服务包", ("等待手动选择服务包", 5)),
    ("启动:", ("启动服务", 90)),
    ("启动游戏助手服务", ("启动服务", 90)),
    ("就绪 (最多", ("启动服务", 90)),
]


def _parse_progress(task: str, line: str) -> tuple[str, float, str]:
    """从子进程输出行中提取 (stage, progress, detail)。"""
    stage = ""
    pct = -1.0

    for keyword, (phase_label, phase_pct) in _DEPLOY_PHASES:
        if keyword in line:
            stage = phase_label
            pct = float(phase_pct)
            break

    # detail: 取行末尾的进度信息，清理掉只有空白/符号的行
    detail = line.strip()
    if detail and len(detail) > 100:
        detail = detail[:100] + "..."

    return stage, pct, detail


# ── 后台执行 ────────────────────────────────────────────────


def _child_env() -> dict:
    """后台子进程一律用 UTF-8 输出。

    否则子进程（deploy.py）在中文 Windows 上按 GBK 写日志，
    而本脚本自己的日志行是 UTF-8，同一个文件混两种编码 → 读取时 UnicodeDecodeError
    → 进度解析和成功标记判定全部静默失效（异常被 except 吞掉）。

    同时把 127.0.0.1/localhost 合并进 no_proxy：Agent 沙盒常注入 http_proxy，
    会把子进程对本机服务（健康检查、浮窗/webserver 访问）的请求也送进代理而
    失败。只影响回环，外网下载照常走代理。no_proxy/NO_PROXY 两个键取并集后
    写成同一份（env 是普通 dict，键区分大小写；两键值不一致时子进程会漏掉
    回环免代理）。与 GameWalkthroughV2/app/env_setup.py 的 ensure_no_proxy 对齐。
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"  # 只改 std 流；不用 PYTHONUTF8，那会连带改掉三方库 open() 的默认编码
    entries: list[str] = []
    for key in ("no_proxy", "NO_PROXY"):
        for item in env.get(key, "").split(","):
            item = item.strip()
            if item and item.lower() not in {e.lower() for e in entries}:
                entries.append(item)
    entries += [h for h in ("127.0.0.1", "localhost")
                if h.lower() not in {e.lower() for e in entries}]
    merged = ",".join(entries)
    env["no_proxy"] = merged
    env["NO_PROXY"] = merged
    return env


def _clear_stale_status():
    """清理旧任务状态，避免残留干扰。"""
    if _STATUS_FILE.exists():
        _STATUS_FILE.unlink(missing_ok=True)


def _launch_background(task: str, cmd: list[str], initial_stage: str = "") -> int | None:
    """启动独立后台子进程，stdout 重定向到日志文件。主进程立即返回。

    返回子进程 pid；启动失败返回 None（调用方必须据此报错，不要照样回 started）。
    """
    _clear_stale_status()
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    task_log_dir = _LOG_SUB_DIR / task
    task_log_dir.mkdir(parents=True, exist_ok=True)

    stdout_log = task_log_dir / "stdout.log"
    log.info("[%s] 后台启动: %s, 日志: %s", task, cmd, stdout_log)

    try:
        with open(stdout_log, "w", encoding="utf-8") as fh:
            proc = subprocess.Popen(
                cmd,
                stdout=fh,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=_child_env(),
            )
    except Exception as e:
        log.error("[%s] 启动子进程失败: %s", task, e)
        _write_status(task, "error", stage="启动失败", detail=str(e),
                      stdout_log=str(stdout_log), started_at=started_at)
        return None

    _write_status(task, "running",
                  stage=initial_stage or "正在部署服务",
                  progress=0, detail="",
                  pid=proc.pid, stdout_log=str(stdout_log), started_at=started_at)

    return proc.pid


# ── 端口检测 ────────────────────────────────────────────────

def is_port_open(host: str = SERVICE_HOST, port: int = SERVICE_PORT,
                 timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


_resolved_port: int | None = None


def _service_answers_on(port: int, timeout: float = 2.0) -> bool:
    """端口上应答的是不是游戏助手服务（响应 dict 且含 code 字段）。

    只探端口通不够：端口可能被别的程序占着。本机调用绕开系统代理，
    同 _post_shutdown。
    """
    opener = request.build_opener(request.ProxyHandler({}))
    try:
        with opener.open(f"http://{SERVICE_HOST}:{port}/vision/service/enable",
                         timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
        return isinstance(body, dict) and "code" in body
    except Exception:
        return False


def resolve_service_port() -> int:
    """服务端实际监听端口：先试新版默认 22919，身份校验通过才用；不通再回退
    旧版 9190（旧服务端已发布出去）。结果缓存；两个端口都无应答时返回 22919，
    让后续请求自然报连接错误。"""
    global _resolved_port
    if _resolved_port is None:
        for port in (SERVICE_PORT, SERVICE_PORT_LEGACY):
            if _service_answers_on(port):
                _resolved_port = port
                break
        else:
            _resolved_port = SERVICE_PORT
    return _resolved_port


def _service_url() -> str:
    return f"http://{SERVICE_HOST}:{resolve_service_port()}"


# ── 健康检查 ────────────────────────────────────────────────

def check_health(host: str | None = None, port: int | None = None) -> bool:
    host = host or SERVICE_HOST
    port = port or resolve_service_port()
    ok = is_port_open(host, port)
    log.info("健康检查 %s:%d -> %s", host, port, "通过" if ok else "失败")
    return ok


def probe_service(attempts: int = 3, interval: float = 4.0) -> str:
    """区分三种情况：ok=游戏助手服务在跑；down=端口没开；foreign=端口开着但不是它。

    只探端口会把"端口被别的程序占用"误判成健康，后续所有请求都打到别人身上，
    报错对小白毫无意义。服务冷启动要十几秒，因此失败会重试几次再下结论。
    新版服务在 22919，旧版（已发布的部署）在 9190：按此顺序探测，命中哪个
    后续请求就打哪个（缓存在 _resolved_port）。
    """
    global _resolved_port
    any_open = False
    for port in (SERVICE_PORT, SERVICE_PORT_LEGACY):
        if not is_port_open(SERVICE_HOST, port):
            continue
        any_open = True
        opener = request.build_opener(request.ProxyHandler({}))  # 绕开系统代理，同 _post_shutdown
        for attempt in range(1, attempts + 1):
            try:
                with opener.open(f"http://{SERVICE_HOST}:{port}/vision/service/enable",
                                 timeout=5) as resp:
                    body = json.loads(resp.read().decode("utf-8", "replace"))
                if isinstance(body, dict) and "code" in body:
                    _resolved_port = port
                    return "ok"
                log.warning("%d 应答不像游戏助手服务: %s", port, str(body)[:120])
            except Exception as e:
                log.info("服务探测第 %d/%d 次未通过: %s", attempt, attempts, e)
            if attempt < attempts:
                time.sleep(interval)
    if not any_open or not any(
            is_port_open(SERVICE_HOST, p) for p in (SERVICE_PORT, SERVICE_PORT_LEGACY)):
        return "down"
    return "foreign"


def _foreign_port_payload() -> dict:
    return {
        "status": "error",
        "message": (f"端口 {SERVICE_PORT}/{SERVICE_PORT_LEGACY} 被其他程序占用（应答的不是游戏助手服务），"
                    "或服务仍在启动中。请关闭占用该端口的程序后重试。"),
    }



def _is_bg_running() -> bool:
    """检查当前是否有后台任务在执行。"""
    data = _read_status()
    if data.get("status") != "running":
        return False
    pid = data.get("pid")
    if pid is not None and _is_pid_alive(int(pid)):
        return True
    # PID 已死但状态未更新 — 检查退出码
    return False


def _check_and_finalize_status(data: dict) -> dict:
    """后台进程已退出时，根据日志内容判定最终状态。"""
    pid = data.get("pid")
    if pid is None:
        return data
    if _is_pid_alive(int(pid)):
        return data

    task = data.get("task", "")

    # deploy 任务不看日志关键词，直接确认服务真的能应答（只看端口会把
    # "9190 被别的程序占用" 误报成部署成功）
    if task == "deploy":
        # 这个判决会落盘且不会再被重新评估（status 只对 running 任务 finalize），
        # 所以不能只探一次就把还在预热的服务判死。
        state = probe_service(attempts=3)
        if state == "ok":
            data["status"] = "done"
            data["progress"] = 100
            data["stage"] = "部署完成，服务已就绪"
        else:
            data["status"] = "error"
            data["stage"] = "部署失败"
            data["detail"] = (_foreign_port_payload()["message"] if state == "foreign"
                              else "部署进程已退出，服务仍不可用，详见部署日志")
            log.warning("[deploy] PID %s 已退出，服务探测=%s", pid, state)
        _write_status(**data)
        return data

    # 出现 deploy 以外的 task 说明状态文件来自旧版本或共享目录里
    # 其它 skill 的任务，无从判定，按失败兜底。
    data["status"] = "error"
    data["stage"] = "任务失败"
    data["detail"] = f"未知任务类型: {task}，进程已退出"
    log.warning("PID %s 已退出，未知任务类型 %s", pid, task)
    _write_status(**data)
    return data


# ── 部署（后台） ──────────────────────────────────────────────

# 合法模型名（需与 deploy.py 的 _COMMON + Splitter 保持一致）
_MODEL_NAMES = {"LLM", "Embedding", "Rerank", "MMR", "ASR", "OCR", "Action", "VLM", "Splitter"}


def _validate_models(models: str) -> str:
    """校验 --models 参数合法性。合法返回空串，非法返回错误信息。"""
    models = (models or "").strip()
    if not models:
        return "必须指定 --models（all / skip / 模型名列表）"
    if models in ("all", "skip"):
        return ""
    names = [n.strip() for n in models.split(",") if n.strip()]
    invalid = [n for n in names if n not in _MODEL_NAMES]
    if invalid:
        return f"非法模型名: {', '.join(invalid)}；可选: all / skip / {', '.join(sorted(_MODEL_NAMES))}"
    return ""


_SKILL_FILE = _SCRIPT_DIR.parent / "SKILL.md"


def _read_skill_defaults(skill_file: Path | None = None) -> dict:
    """从 SKILL.md 的 frontmatter 读 models / install_dir。

    这两个值本来就声明在 SKILL.md 里。让脚本自己读，agent 就不必每条命令
    原样转述一遍，也不会出现各命令传参不一致而读错状态文件。读不到（文件
    缺失或格式不符）就返回空，由 CLI 参数兜底。
    """
    path = skill_file or _SKILL_FILE
    values: dict = {}
    try:
        lines = path.read_text(encoding="utf-8").lstrip("﻿").splitlines()  # 记事本存的 UTF-8 带 BOM
    except OSError:
        return values
    if not lines or lines[0].strip() != "---":
        return values
    for line in lines[1:]:
        if line.strip() == "---":
            break
        # 只认顶层键（不允许缩进），否则 frontmatter 里嵌套块中的同名键会被当成顶层值
        m = re.match(r"^(models|install_dir)\s*:\s*(.*)$", line)
        if not m:
            continue
        # 只有 # 前面有空白才当行内注释，否则 "D:/Game#1" 这类路径会被截断
        raw = re.split(r"\s+#", m.group(2), maxsplit=1)[0].strip()
        values[m.group(1)] = raw.strip("\"'")
    return values


def _validate_install_dir(install_dir: str) -> str:
    """校验 install_dir（预装服务目录）有效性。空串表示用默认路径，返回空串；非法返回错误信息。

    「目录不存在 / 目录里还没有 exe」不再算致命错误：这两种情况会照常透传给
    deploy.py，由其弹窗询问用户安装方式（自动下载 / 指定本地服务包 / 取消）。
    只有指向一个普通文件这种真正非法的路径才直接报错。
    """
    install_dir = (install_dir or "").strip()
    if not install_dir:
        return ""
    p = Path(install_dir)
    if p.exists() and not p.is_dir():
        return f"预装路径不是目录: {p}"
    return ""


def _deploy_cmd(models: str, install_dir: str) -> tuple[list[str] | None, str, str]:
    """拼部署命令，返回 (cmd, 模型策略描述, 错误信息)。cmd 为 None 表示不可执行。"""
    err = _validate_models(models)
    if err:
        return None, "", err
    if not DEPLOY_SCRIPT.exists():
        return None, "", f"部署脚本不存在: {DEPLOY_SCRIPT}"

    cmd = [sys.executable, str(DEPLOY_SCRIPT), "--mode", "auto-fallback"]
    if install_dir:
        cmd += ["--install-dir", install_dir]
    if models == "all":
        strategy = "全部下载"
    elif models == "skip":
        cmd += ["--skip-models"]
        strategy = "跳过下载"
    else:
        # 已通过 _validate_models 校验，此处是合法模型名列表
        cmd += ["--models", models]
        strategy = f"只下载 {models}"
    return cmd, strategy, ""


def deploy(models: str = "", install_dir: str = "") -> None:
    err = _validate_install_dir(install_dir)
    if err:
        _write_status("deploy", "error", stage="预装路径无效", detail=err)
        print(json.dumps({"status": "error", "message": err}, ensure_ascii=False))
        return

    if _is_bg_running():
        log.warning("已有后台任务在运行")
        print(json.dumps({"status": "busy", "message": "已有后台任务在运行，请等待完成"},
                         ensure_ascii=False))
        return

    cmd, strategy, err = _deploy_cmd(models, install_dir)
    if cmd is None:
        _write_status("deploy", "error", stage="无法启动部署", detail=err)
        print(json.dumps({"status": "error", "message": err}, ensure_ascii=False))
        return

    log.info("后台启动部署: %s --mode auto-fallback（模型策略: %s）", DEPLOY_SCRIPT, strategy)
    if _launch_background("deploy", cmd) is None:
        print(json.dumps({"status": "error",
                          "message": "部署进程启动失败: " + _read_status().get("detail", "")},
                         ensure_ascii=False))
        return
    print(json.dumps({"status": "started", "task": "deploy", "models": strategy},
                     ensure_ascii=False))


# ── 关闭服务 ────────────────────────────────────────────────

def _post_shutdown(endpoint: str) -> bool:
    url = f"{_service_url()}{endpoint}"
    data = json.dumps({}).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"})
    # 本机服务调用绕过系统代理：urllib 默认 getproxies() 在 Windows 会读注册表代理，
    # 把 127.0.0.1 请求送进代理 → 403 Forbidden。与 deploy.py 的 Vision 修复对齐。
    opener = request.build_opener(request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if body.get("code") == "ok":
                log.info("关闭成功: %s -> %s", endpoint, body)
                return True
            log.warning("关闭返回非 ok: %s -> %s", endpoint, body)
            return False
    except URLError as e:
        log.warning("关闭请求失败: %s -> %s", endpoint, e)
        return False


# ── 关闭 BARDemo（服务关闭前先做：Demo 依赖服务端，顺序不要反） ──

def _stop_bardemo() -> bool:
    """结束 BARDemo.exe 进程树；未在运行时静默跳过，不报错。

    返回是否检测到并结束（对应 shutdown 返回值里的 client_stopped）。
    """
    try:
        probe = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq BARDemo.exe", "/NH"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception as e:
        log.warning("探测 BARDemo 进程失败: %s", e)
        return False
    if "BARDemo.exe" not in probe.stdout:
        return False
    try:
        subprocess.run(["taskkill", "/IM", "BARDemo.exe", "/F", "/T"],
                       capture_output=True, text=True, timeout=10)
        log.info("已结束 BARDemo.exe 进程")
    except Exception as e:
        log.warning("taskkill BARDemo 失败: %s", e)
    return True


def shutdown() -> int:
    log.info("正在关闭服务...")
    client_stopped = _stop_bardemo()

    if not any(is_port_open(SERVICE_HOST, p) for p in (SERVICE_PORT, SERVICE_PORT_LEGACY)):
        log.info("服务未在运行（端口不可达）")
        print(json.dumps({"status": "done", "client_stopped": client_stopped,
                          "message": "BARDemo 已关闭，服务本来就没在运行"
                          if client_stopped else "BARDemo 未在运行，服务也未在运行"},
                         ensure_ascii=False))
        return 0

    if _post_shutdown("/server/shutdown"):
        print(json.dumps({"status": "done", "client_stopped": client_stopped,
                          "message": "BARDemo 与服务已关闭"}, ensure_ascii=False))
        return 0

    log.info("尝试强制关闭 /server/shutdown_kill ...")
    if _post_shutdown("/server/shutdown_kill"):
        print(json.dumps({"status": "done", "client_stopped": client_stopped,
                          "message": "BARDemo 已关闭，服务已强制关闭"}, ensure_ascii=False))
        return 0

    log.error("关闭服务失败")
    print(json.dumps({"status": "error", "client_stopped": client_stopped,
                      "message": "关闭服务失败"}, ensure_ascii=False))
    return 1


# ── ensure ──────────────────────────────────────────────────

def ensure(models: str = "", install_dir: str = "") -> int:
    """健康检查 -> 不通过则后台部署 + 等待就绪（不限时轮询）。"""
    if check_health():
        print(json.dumps({"status": "healthy", "port": resolve_service_port(),
                          "message": "服务已在运行"}, ensure_ascii=False))
        return 0

    log.info("服务未运行，后台启动部署...")
    deploy(models, install_dir)
    while True:
        if check_health():
            print(json.dumps({"status": "healthy", "port": resolve_service_port(),
                              "message": "部署完成，服务已就绪"}, ensure_ascii=False))
            return 0
        data = _read_status()
        if data.get("task") == "deploy" and data.get("status") == "error":
            msg = "部署失败: " + data.get("detail", "服务未能就绪")
            print(json.dumps({"status": "error", "message": msg}, ensure_ascii=False))
            return 1
        # 部署进程已退出但端口不通 → 用户可能取消了部署
        pid = data.get("pid")
        if pid and not _is_pid_alive(int(pid)):
            print(json.dumps({"status": "error", "message": "部署进程已退出，可能用户取消了部署"}, ensure_ascii=False))
            return 1
        time.sleep(30)
    return 1


# ── 状态查询 ────────────────────────────────────────────────

def status() -> None:
    data = _read_status()
    if data.get("status") == "running":
        data = _check_and_finalize_status(data)
    # 只有确实还在跑才去解析日志：任务已终结时再覆盖 stage/progress，会出现
    # "打给 agent 的" 和 "落盘的" 不一致，同一个已完成任务在两次轮询间反复横跳
    if data.get("status") == "running":
        stdout_log = data.get("stdout_log", "")
        task = data.get("task", "")
        if stdout_log:
            try:
                best_pct = -1.0
                with open(stdout_log, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        stripped = line.rstrip("\n\r")
                        if stripped:
                            stage, pct, detail = _parse_progress(task, stripped)
                            # 进度只增不减：日志里晚出现的行未必是更靠后的阶段
                            # （如模型逐个完成时的 "MMR 下载完成"），倒退会误导用户。
                            # stage 跟着进度走，避免出现 60% 却显示"下载服务包"。
                            if pct >= 0 and pct >= best_pct:
                                best_pct = pct
                                data["progress"] = pct
                                if stage:
                                    data["stage"] = stage
                            if detail:
                                data["detail"] = detail
            except Exception:
                pass
    print(json.dumps(data, ensure_ascii=False))


# ── ensure-demo（Demo 资产就绪）─────────────────────────────

# Demo 客户端与第三方组件不随 skill 分发：缺哪个包就从 ModelScope 数据集
# 下载哪个 7z，解压到 skill 根目录（包内自带同名顶层目录，正好落位）。
# 换包只改下面的文件名；markers 与包内关键文件一一对应，作为就绪判据。
DEMO_DATASET_URL = (
    "https://modelscope.cn/api/v1/datasets/xmcintel/"
    "game-assistant-boss-action-recognition-data/repo?Revision=master&FilePath="
)
DEMO_PACKAGES = [
    {
        "file": "BARDemo.7z",
        "markers": [_SKILL_ROOT / "BARDemo" / "BARDemo.exe"],
    },
    {
        "file": "thirdparty.7z",
        "markers": [
            _SKILL_ROOT / "thirdparty" / "mpv" / "mpv.exe",
            _SKILL_ROOT / "thirdparty" / "speedhack" / "SpeedHack.dll",
        ],
    },
]


def _demo_package_ready(pkg: dict) -> bool:
    return all(marker.exists() for marker in pkg["markers"])


# ── ensure-demo 进度窗口（样式对齐 deploy.py 的部署进度窗口）──

_UI_FONTS = ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "SimSun")


def _pick_font(families: tuple, size: int, root) -> tuple:
    import tkinter.font as tkfont
    try:
        available = set(tkfont.families(root))
    except Exception:
        return families[-1], size
    for f in families:
        if f in available:
            return f, size
    return families[-1], size


def _fmt_mb(n: float) -> str:
    return f"{n / (1024 * 1024):.0f}MB"


class _DemoProgressWindow:
    """Demo 资产下载进度窗口：每个待下载包一行「文件名 + 进度条 + 速度」。

    样式与 deploy.py 的 ProgressDialog 同风格（浅底、状态标签、ttk 进度条、
    完成倒计时自动关窗）。工作线程经 report() 上报事件（queue 线程安全），
    主循环每 150ms 取最新值刷新。用户点 X = 取消下载：置 cancel 事件后关窗，
    工作线程在下一个分片中止，最终仍会打印一行 error JSON，agent 契约不破。
    """

    def __init__(self, files: list):
        import tkinter as tk
        from tkinter import ttk

        self._tk = tk
        self.q: "queue.Queue[dict]" = queue.Queue()
        self.cancel = threading.Event()
        self._close_at: float | None = None

        self.root = tk.Tk()
        self.root.title("Boss 招式识别 Demo 资产下载")
        w, h = 560, 66 + 34 * len(files)
        self.root.geometry(f"{w}x{h}")
        self.root.configure(bg="#fafafa")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_user_close)

        ui_font = _pick_font(_UI_FONTS, 10, self.root)
        self._status_var = tk.StringVar(value="正在下载 Demo 资产...")
        tk.Label(self.root, textvariable=self._status_var, font=ui_font,
                 anchor="w", justify="left", wraplength=w - 24,
                 bg="#fafafa", fg="#333333"
                 ).place(x=12, y=12, width=w - 24, height=28)

        self._bars, self._texts = {}, {}
        for i, name in enumerate(files):
            y = 48 + 34 * i
            tk.Label(self.root, text=name, font=ui_font, anchor="w",
                     bg="#fafafa", fg="#333333"
                     ).place(x=12, y=y, width=130, height=24)
            bar = ttk.Progressbar(self.root, mode="determinate", maximum=100)
            bar.place(x=150, y=y + 2, width=240, height=18)
            self._bars[name] = bar
            txt = tk.Label(self.root, text="等待中...", font=ui_font, anchor="w",
                           bg="#fafafa", fg="#333333")
            txt.place(x=400, y=y, width=w - 412, height=24)
            self._texts[name] = txt

        # 居中（同 ProgressDialog._center）
        self.root.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    def report(self, ev: dict):
        """工作线程调用：投递进度/阶段/完成事件。"""
        self.q.put(ev)

    def _on_user_close(self):
        self.cancel.set()
        self.close()

    def close(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self, work, pending: list, result: dict):
        """起工作线程跑 work(pending, result, report, cancel)，主循环刷窗。"""
        t = threading.Thread(target=work,
                             args=(pending, result, self.report, self.cancel),
                             daemon=True)
        t.start()
        self.root.after(150, self._pump)
        self.root.mainloop()
        t.join(timeout=15)

    def _pump(self):
        try:
            while True:
                ev = self.q.get_nowait()
                et = ev.get("type")
                if et == "download":
                    done, total, speed = ev["done"], ev["total"], ev["speed"]
                    bar, txt = self._bars[ev["file"]], self._texts[ev["file"]]
                    if total:
                        bar.configure(mode="determinate")
                        bar["value"] = done / total * 100
                        txt.configure(text=f"{_fmt_mb(done)}/{_fmt_mb(total)}  {speed:.1f}MB/s")
                    else:
                        txt.configure(text=f"{_fmt_mb(done)}  {speed:.1f}MB/s")
                elif et == "stage":
                    self._status_var.set(ev["text"])
                elif et == "done":
                    self._close_at = time.monotonic() + 5
                    self._status_var.set("Demo 资产就绪，窗口即将自动关闭。")
                elif et == "error":
                    self._close_at = time.monotonic() + 10
                    self._status_var.set(f"错误: {ev.get('message', '')}")
        except queue.Empty:
            pass

        if self._close_at is not None and time.monotonic() >= self._close_at:
            self.close()
            return
        self.root.after(150, self._pump)


# 下载+校验的总尝试次数（与 deploy.py 下载服务包的重试思路对齐）
_DEMO_DOWNLOAD_RETRIES = 3


def _verify_demo_package(path: Path) -> bool:
    """下载后轻量校验：7z 能打开且文件列表非空，防「大小对、内容坏」。"""
    import py7zr
    try:
        with py7zr.SevenZipFile(path, "r") as sz:
            return bool(sz.list())
    except Exception:
        return False


def _download_once(url: str, dest: Path, progress_cb=None) -> None:
    """单次下载：先落 .part 再原子改名，Content-Length 校验防半成品。

    progress_cb(done, total, speed_bytes_per_sec) 每分片回调一次（1MB）。
    走 urllib 默认代理（Windows 下 getproxies() 读注册表代理），与
    deploy.py 下载服务包/模型同一网络环境，无需额外配置。
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    log.info("下载: %s", url)
    started = time.monotonic()
    with request.urlopen(url, timeout=60) as resp, open(part, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress_cb:
                elapsed = time.monotonic() - started
                progress_cb(done, total, done / elapsed if elapsed > 0 else 0.0)
    if total and done != total:
        raise RuntimeError(f"下载不完整: {done}/{total} 字节")
    part.replace(dest)


def _download_demo_package(url: str, dest: Path, progress_cb=None) -> None:
    """下载 + 开包校验 + 按需重试，全失败抛最后一个异常。

    Content-Length 比对防截断，下载后 _verify_demo_package 防内容损坏
    （与 deploy.py 的 verify_cb 同款思路）；坏档不留正式文件名，重试
    从头下载，最多 _DEMO_DOWNLOAD_RETRIES 次。progress_cb 透传每次尝试。
    """
    last_exc: Exception | None = None
    for attempt in range(1, _DEMO_DOWNLOAD_RETRIES + 1):
        try:
            _download_once(url, dest, progress_cb=progress_cb)
            if not _verify_demo_package(dest):
                raise RuntimeError("7z 开包校验失败（疑似内容损坏）")
            return
        except Exception as exc:
            last_exc = exc
            dest.unlink(missing_ok=True)
            if attempt < _DEMO_DOWNLOAD_RETRIES:
                log.warning("第 %d/%d 次下载失败，将重试: %s",
                            attempt, _DEMO_DOWNLOAD_RETRIES, exc)
    raise last_exc  # type: ignore[misc]


def _ensure_demo_work(pending: list, result: dict, report=None, cancel=None) -> None:
    """下载+解压的实体工作，结果写入 result（report/cancel 由进度窗口注入）。

    多个包并行下载（I/O 密集，线程池即可），全部到齐后按包顺序串行解压。
    py7zr 对已存在文件静默跳过而非覆盖（与 deploy.py 装帧库同款行为），
    半途损坏的旧目录里缺的文件会被补齐，已有文件不受影响。
    """
    import tempfile
    from concurrent.futures import ThreadPoolExecutor

    import py7zr

    def emit(ev: dict):
        if report:
            report(ev)

    def check_cancel():
        if cancel is not None and cancel.is_set():
            raise RuntimeError("用户取消了下载")

    try:
        with tempfile.TemporaryDirectory(prefix="bardemo_assets_") as td:
            def fetch(pkg: dict) -> Path:
                check_cancel()
                dest = Path(td) / pkg["file"]

                def on_prog(done, total, speed):
                    check_cancel()
                    emit({"type": "download", "file": pkg["file"],
                          "done": done, "total": total, "speed": speed})

                _download_demo_package(DEMO_DATASET_URL + pkg["file"], dest,
                                       progress_cb=on_prog)
                return dest

            with ThreadPoolExecutor(max_workers=len(pending)) as pool:
                dests = list(pool.map(fetch, pending))

            for pkg, dest in zip(pending, dests):
                check_cancel()
                emit({"type": "stage", "text": f"解压 {pkg['file']}..."})
                log.info("解压 %s → %s", pkg["file"], _SKILL_ROOT)
                with py7zr.SevenZipFile(dest, "r") as sz:
                    sz.extractall(path=_SKILL_ROOT)
    except Exception as exc:
        result["status"] = "error"
        result["message"] = f"Demo 资产下载/解压失败: {exc}"
        emit({"type": "error", "message": result["message"]})
        return

    missing = [p["file"] for p in DEMO_PACKAGES if not _demo_package_ready(p)]
    if missing:
        result["status"] = "error"
        result["message"] = f"解压完成但关键文件仍缺失: {', '.join(missing)}（请检查数据集包内容）"
        emit({"type": "error", "message": result["message"]})
        return
    result["status"] = "ready"
    emit({"type": "done", "message": "Demo 资产已就绪"})


def ensure_demo() -> int:
    """确保 BARDemo/ 与 thirdparty/ 就绪：缺哪个包下载哪个，幂等。

    弹进度窗口（样式对齐 deploy.py 的部署进度窗口，每包一行进度，完成
    倒计时自动关窗，点 X = 取消下载）；tkinter 不可用时静默降级为纯 CLI。
    stdout 契约不变：始终一行 JSON。
    """
    pending = [p for p in DEMO_PACKAGES if not _demo_package_ready(p)]
    if not pending:
        log.info("Demo 资产已就绪")
        print(json.dumps({"status": "ready"}, ensure_ascii=False))
        return 0

    result: dict = {"status": "error", "message": ""}
    try:
        gui = _DemoProgressWindow([p["file"] for p in pending])
    except Exception as exc:
        log.warning("进度窗口不可用，降级为无窗下载: %s", exc)
        gui = None

    if gui is None:
        _ensure_demo_work(pending, result)
    else:
        gui.run(_ensure_demo_work, pending, result)

    if result["status"] == "ready":
        log.info("Demo 资产已就绪")
        print(json.dumps({"status": "ready"}, ensure_ascii=False))
        return 0
    if not result["message"]:
        result["message"] = "Demo 资产准备失败（未知原因）"
    log.error("ensure-demo 失败: %s", result["message"])
    print(json.dumps(result, ensure_ascii=False))
    return 1


# ── CLI ─────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="游戏助手服务管理")
    parser.add_argument(
        "action",
        choices=["health", "deploy", "shutdown", "status", "ensure", "ensure-demo"],
        help=(
            "health=健康检查 | deploy=后台部署 | shutdown=关闭服务（先关 BARDemo） | "
            "status=查进度 | ensure=检查并按需部署 | ensure-demo=确保 Demo 资产就绪"
        ),
    )
    parser.add_argument("--models", default="",
                        help="覆盖 SKILL.md 的 models：all=全部，skip=跳过，<模型名列表>=只下载指定（如 MMR,LLM）")
    parser.add_argument("--install-dir", default="",
                        help="覆盖 SKILL.md 的 install_dir（空=默认 %%LOCALAPPDATA%%\\GameAssistant）")
    args = parser.parse_args()

    # 默认值来自 SKILL.md frontmatter，命令行显式传值则覆盖它
    skill_defaults = _read_skill_defaults()
    models = args.models.strip() or skill_defaults.get("models", "")
    install_dir = args.install_dir.strip() or skill_defaults.get("install_dir", "")
    # 支持 %LOCALAPPDATA% 这类环境变量路径：bash/cmd/PowerShell 下 %VAR% 并不总是会被
    # shell 展开，这里统一展开成真实路径，再交给校验、数据目录与子进程传参。
    install_dir = os.path.expandvars(install_dir).strip()

    # 只有可能触发部署的命令才强校验预装目录：status / health / shutdown 只是读状态，
    # 不该因为预装目录里还没有 exe 就整个失败。
    if args.action in ("deploy", "ensure"):
        install_dir_err = _validate_install_dir(install_dir)
        if install_dir_err:
            print(json.dumps({"status": "error", "message": install_dir_err}, ensure_ascii=False))
            return 2

    _apply_data_dir(install_dir)

    if args.action == "health":
        state = probe_service()
        if state == "foreign":
            print(json.dumps(_foreign_port_payload(), ensure_ascii=False))
            return 1
        ok = state == "ok"
        result = {"status": "healthy" if ok else "unhealthy"}
        if ok:
            result["port"] = resolve_service_port()
        print(json.dumps(result, ensure_ascii=False))
        return 0 if ok else 1

    if args.action == "deploy":
        deploy(models, install_dir)
        return 0

    if args.action == "shutdown":
        return shutdown()

    if args.action == "status":
        status()
        return 0

    if args.action == "ensure":
        return ensure(models, install_dir)

    if args.action == "ensure-demo":
        return ensure_demo()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # 兜底：agent 拿到的永远是一条可解析的 JSON，而不是 traceback
        logging.getLogger("service_manager").exception("未预期的错误")
        print(json.dumps({"status": "error", "message": f"脚本异常: {exc}"}, ensure_ascii=False))
        sys.exit(1)
