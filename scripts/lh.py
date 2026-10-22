#!/usr/bin/env python3
"""腾讯云轻量应用服务器 (Lighthouse) 远程读取工具。

通过 SSH 连接一台腾讯云轻量应用服务器，执行只读巡检、命令执行与文件传输。
配置来自 .env 文件（LH_HOST / LH_USER / LH_PASSWORD 等），不硬编码任何凭据。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import textwrap
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILES = [
    SKILL_DIR / ".env",
    Path.cwd() / ".env",
]

ENV_TEMPLATE_KEYS = [
    ("LH_HOST", "服务器公网 IP（腾讯云控制台 → 轻量应用服务器 → 实例详情）"),
    ("LH_PORT", "SSH 端口，默认 22"),
    ("LH_USER", "登录用户名，Linux 镜像一般为 root 或 ubuntu"),
    ("LH_PASSWORD", "登录密码（控制台可重置），使用密钥登录时留空"),
    ("LH_KEY_PATH", "可选：私钥文件路径，配置后优先于密码登录"),
    ("LH_TIMEOUT", "连接超时秒数，默认 15"),
]

MASK = "******"

# Git Bash（MSYS2）会把它认为的 POSIX 绝对路径改写成 Windows 路径：
#   /home/Agent/x -> E:/.../PortableGit/home/Agent/x
#   /tmp/x        -> C:/Users/<user>/AppData/Local/Temp/x
# 远端路径参数需要还原，否则会变成「本地找不到文件」。
_MSYS_GIT_RE = re.compile(r"^[A-Za-z]:[\\/].*?[\\/](?:PortableGit|Git|msys64)[\\/](.+)$", re.I)
_MSYS_TMP_RE = re.compile(
    r"^[A-Za-z]:[\\/]Users[\\/][^\\/]+[\\/]AppData[\\/]Local[\\/]Temp[\\/](.+)$", re.I
)


def desquash_remote(path: str) -> str:
    """还原 Git Bash 对远端绝对路径的改写。"""
    if not path:
        return path
    normalized = path.replace("\\", "/")
    match = _MSYS_GIT_RE.match(normalized)
    if match:
        return "/" + match.group(1)
    match = _MSYS_TMP_RE.match(normalized)
    if match:
        return "/tmp/" + match.group(1)
    return path


# ---------------------------------------------------------------- 配置读取


def parse_env_file(path: Path) -> dict:
    """解析 .env 文件；支持 # 注释、引号、export 前缀。"""
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.lower().startswith("export "):
            line = line[7:].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            data[key] = value
    return data


def load_config(env_file: str | None = None) -> tuple[dict, Path | None]:
    """按优先级合并：命令行指定 > 环境变量 > .env 文件。"""
    cfg: dict[str, str] = {}
    source: Path | None = None

    candidates: list[Path] = []
    if env_file:
        candidates.append(Path(env_file).expanduser())
    elif os.environ.get("LH_ENV_FILE"):
        candidates.append(Path(os.environ["LH_ENV_FILE"]).expanduser())
    candidates.extend(DEFAULT_ENV_FILES)

    for candidate in candidates:
        if candidate.is_file():
            cfg.update(parse_env_file(candidate))
            if source is None:
                source = candidate
            break

    for key, _ in ENV_TEMPLATE_KEYS:
        if os.environ.get(key):
            cfg[key] = os.environ[key]
    return cfg, source


def normalize(cfg: dict) -> dict:
    return {
        "host": (cfg.get("LH_HOST") or "").strip(),
        "port": int((cfg.get("LH_PORT") or "22").strip() or 22),
        "user": (cfg.get("LH_USER") or "root").strip(),
        "password": cfg.get("LH_PASSWORD") or "",
        "key_path": (cfg.get("LH_KEY_PATH") or "").strip(),
        "timeout": int((cfg.get("LH_TIMEOUT") or "15").strip() or 15),
        "name": (cfg.get("LH_NAME") or "").strip(),
    }


def missing_required(c: dict) -> list[str]:
    gaps = []
    if not c["host"]:
        gaps.append("LH_HOST")
    if not c["user"]:
        gaps.append("LH_USER")
    if not c["password"] and not c["key_path"]:
        gaps.append("LH_PASSWORD（或 LH_KEY_PATH）")
    return gaps


def print_env_help(source: Path | None, gaps: list[str]) -> None:
    print("未找到可用的服务器配置。" if source is None else f"配置文件 {source} 缺少必要字段。")
    print()
    print("请先在 skill 目录创建 .env 文件（模板见 .env.example），填写以下三项：")
    print()
    for key, desc in ENV_TEMPLATE_KEYS:
        print(f"  {key:<14}{desc}")
    print()
    print("示例：")
    print(textwrap.indent(
        "LH_HOST=123.45.67.89\n"
        "LH_PORT=22\n"
        "LH_USER=root\n"
        "LH_PASSWORD=你的服务器密码\n"
        "LH_TIMEOUT=15",
        "  ",
    ))
    print()
    if gaps:
        print("当前缺失：" + "、".join(gaps))
    print()
    print("提示：拿到 IP / 用户名 / 密码 后，可直接让助手写入 .env，或运行")
    print("      python scripts/lh.py init --host <IP> --user <用户名> --password <密码>")


# ---------------------------------------------------------------- SSH 连接


def require_paramiko():
    try:
        import paramiko  # noqa: F401
    except ImportError:
        print("缺少依赖 paramiko，请先安装：")
        print("  python -m pip install -r scripts/requirements.txt")
        sys.exit(3)
    import paramiko

    return paramiko


def connect(c: dict):
    paramiko = require_paramiko()
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    kwargs = {
        "hostname": c["host"],
        "port": c["port"],
        "username": c["user"],
        "timeout": c["timeout"],
        "banner_timeout": c["timeout"],
        "auth_timeout": c["timeout"],
        "allow_agent": False,
        "look_for_keys": False,
    }
    if c["key_path"]:
        kwargs["key_filename"] = str(Path(c["key_path"]).expanduser())
    else:
        kwargs["password"] = c["password"]

    try:
        client.connect(**kwargs)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 连接失败：{type(exc).__name__}: {exc}")
        print("排查建议：")
        print("  1. 确认 IP 正确、实例已开机（控制台 → 实例状态）")
        print("  2. 确认防火墙/安全组放通 SSH 端口（默认 22）")
        print("  3. 确认用户名与镜像匹配（Ubuntu→ubuntu，CentOS/Debian 等→root）")
        print("  4. 密码错误请在控制台重置密码后重试")
        sys.exit(4)

    client.get_transport().set_keepalive(30)
    return client


def run_remote(client, command: str, timeout: int = 120):
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    stdin.close()
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out, err


def emit(rc: int, out: str, err: str) -> int:
    if out:
        sys.stdout.write(out if out.endswith("\n") else out + "\n")
    if err:
        sys.stderr.write(err if err.endswith("\n") else err + "\n")
    return rc


# ---------------------------------------------------------------- 各命令实现


INFO_SCRIPT = r"""
echo "### 主机名"; hostname 2>/dev/null || true
echo "### 系统"; (. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME") || uname -a
echo "### 内核"; uname -r 2>/dev/null || true
echo "### 运行时长"; uptime -p 2>/dev/null || uptime 2>/dev/null || true
echo "### 负载"; cat /proc/loadavg 2>/dev/null | cut -d' ' -f1-3 || true
echo "### CPU"; echo "核心数: $(nproc 2>/dev/null || echo '?')"; grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2 | sed 's/^ *//' || true
echo "### 内存"; free -h 2>/dev/null || true
echo "### 磁盘"; df -h -x tmpfs -x devtmpfs 2>/dev/null || df -h 2>/dev/null || true
echo "### 内网 IP"; hostname -I 2>/dev/null || true
echo "### 占用最高进程"; ps -eo pid,comm,%cpu,%mem --sort=-%cpu 2>/dev/null | head -6 || true
echo "### 最近登录"; last -n 5 2>/dev/null || true
"""


def cmd_doctor(c: dict, source: Path | None) -> int:
    print("== 配置检查 ==")
    print(f"配置文件   : {source if source else '未找到（.env 缺失）'}")
    if not c["host"]:
        print_env_help(source, missing_required(c))
        return 2

    print(f"主机       : {c['host']}:{c['port']}")
    print(f"用户       : {c['user']}")
    auth = f"密钥 {c['key_path']}" if c["key_path"] else f"密码 {MASK}"
    print(f"认证方式   : {auth}")

    gaps = missing_required(c)
    if gaps:
        print_env_help(source, gaps)
        return 2

    print()
    print("== 依赖检查 ==")
    try:
        import paramiko

        print(f"paramiko   : {paramiko.__version__}")
    except ImportError:
        print("paramiko   : 未安装 → python -m pip install -r scripts/requirements.txt")
        return 3

    print()
    print("== 端口连通性 ==")
    sock = socket.socket()
    sock.settimeout(min(c["timeout"], 8))
    try:
        sock.connect((c["host"], c["port"]))
        print(f"TCP {c['host']}:{c['port']} 可连接")
    except Exception as exc:  # noqa: BLE001
        print(f"TCP 连接失败：{exc}")
        print("检查安全组/防火墙是否放通该端口。")
        return 4
    finally:
        sock.close()

    print()
    print("== SSH 登录与基本信息 ==")
    client = connect(c)
    try:
        rc, out, err = run_remote(
            client,
            "printf 'whoami: '; whoami; printf 'hostname: '; hostname; "
            "printf 'kernel: '; uname -sr; printf 'uptime: '; uptime -p 2>/dev/null || uptime",
        )
        emit(rc, out, err)
    finally:
        client.close()
    print("配置可用，可以直接查询服务器。")
    return 0


def cmd_env(c: dict, source: Path | None) -> int:
    print(f"# 来源: {source if source else '无 .env（仅环境变量或未配置）'}")
    print(f"LH_HOST={c['host'] or '(未设置)'}")
    print(f"LH_PORT={c['port']}")
    print(f"LH_USER={c['user'] or '(未设置)'}")
    print(f"LH_PASSWORD={MASK if c['password'] else '(未设置)'}")
    print(f"LH_KEY_PATH={c['key_path'] or '(未设置)'}")
    print(f"LH_TIMEOUT={c['timeout']}")
    gaps = missing_required(c)
    if gaps:
        print(f"# 缺失: {'、'.join(gaps)}")
        return 2
    return 0


def cmd_info(c: dict) -> int:
    client = connect(c)
    try:
        rc, out, err = run_remote(client, INFO_SCRIPT)
    finally:
        client.close()
    if out:
        for block in out.split("### "):
            block = block.strip()
            if not block:
                continue
            title, _, body = block.partition("\n")
            print(f"[{title}]")
            if body.strip():
                print(body.rstrip())
            print()
    return emit(rc, "", err)


def cmd_exec(c: dict, command: str, as_json: bool, timeout: int = 120) -> int:
    client = connect(c)
    try:
        rc, out, err = run_remote(client, command, timeout=timeout)
    finally:
        client.close()
    if as_json:
        print(json.dumps({"rc": rc, "stdout": out, "stderr": err}, ensure_ascii=False, indent=2))
        return rc
    emit(rc, out, err)
    if rc != 0:
        print(f"# 退出码 {rc}")
    return rc


def cmd_tail(c: dict, path: str, lines: int) -> int:
    client = connect(c)
    try:
        rc, out, err = run_remote(client, f"tail -n {int(lines)} {sh_quote(path)}")
    finally:
        client.close()
    return emit(rc, out, err)


def cmd_upload(c: dict, local: str, remote: str) -> int:
    require_paramiko()
    client = connect(c)
    try:
        sftp = client.open_sftp()
        sftp.put(local, remote)
        sftp.close()
        print(f"已上传 {local} → {remote}")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 上传失败：{type(exc).__name__}: {exc}")
        return 5
    finally:
        client.close()
    return 0


def cmd_download(c: dict, remote: str, local: str) -> int:
    require_paramiko()
    client = connect(c)
    try:
        sftp = client.open_sftp()
        sftp.get(remote, local)
        sftp.close()
        print(f"已下载 {remote} → {local}")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 下载失败：{type(exc).__name__}: {exc}")
        return 5
    finally:
        client.close()
    return 0


def cmd_init(args) -> int:
    target = SKILL_DIR / ".env"
    if target.exists() and not args.force:
        print(f"{target} 已存在，如需覆盖请加 --force")
        return 1

    values = {
        "LH_HOST": args.host or "",
        "LH_PORT": args.port or "22",
        "LH_USER": args.user or "root",
        "LH_PASSWORD": args.password or "",
        "LH_KEY_PATH": args.key_path or "",
        "LH_TIMEOUT": args.timeout or "15",
    }
    content = "\n".join([
        "# 腾讯云轻量应用服务器连接配置（此文件已被 .gitignore 忽略，不会提交）",
        *[f"{k}={v}" for k, v in values.items()],
        "",
    ])
    target.write_text(content, encoding="utf-8")
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    print(f"已写入 {target}")
    if not values["LH_HOST"] or (not values["LH_PASSWORD"] and not values["LH_KEY_PATH"]):
        print("警告：IP 或凭据仍为空，请补齐后运行 doctor 验证。")
        return 1
    print("下一步：python scripts/lh.py doctor")
    return 0


def sh_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


# ---------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lh",
        description="腾讯云轻量应用服务器（Lighthouse）远程读取工具",
    )
    p.add_argument("--env-file", help="指定 .env 路径（默认读取 skill 目录或当前目录）")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("doctor", help="检查配置、依赖与连通性（首次使用先跑这个）")
    sub.add_parser("env", help="打印当前生效配置（密码已脱敏）")

    sub.add_parser("info", help="主机概览：系统/CPU/内存/磁盘/负载/进程")

    e = sub.add_parser("exec", help="在服务器上执行命令")
    e.add_argument("command", help="要执行的命令")
    e.add_argument("--json", action="store_true", help="以 JSON 输出 rc/stdout/stderr")
    e.add_argument("-t", "--timeout", type=int, default=120,
                   help="命令超时秒数，默认 120（构建等长任务可调大）")

    def path_cmd(name, help_text):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("path", help="远程路径")
        return sp

    path_cmd("ls", "列出远程目录")
    path_cmd("cat", "读取远程文件内容")
    c = path_cmd("tail", "查看远程文件末尾（日志）")
    c.add_argument("-n", "--lines", type=int, default=50, help="行数，默认 50")

    sub.add_parser("ps", help="CPU 占用最高的进程")
    sub.add_parser("df", help="磁盘占用")
    sub.add_parser("mem", help="内存占用")
    sub.add_parser("services", help="运行中的 systemd 服务")
    sub.add_parser("docker", help="Docker 容器状态（未安装则提示）")
    sub.add_parser("ports", help="监听中的端口")
    sub.add_parser("firewall", help="防火墙 / ufw 规则")

    u = sub.add_parser("upload", help="上传本地文件到服务器")
    u.add_argument("local")
    u.add_argument("remote")

    d = sub.add_parser("download", help="从服务器下载文件")
    d.add_argument("remote")
    d.add_argument("local")

    i = sub.add_parser("init", help="生成 .env 文件")
    i.add_argument("--host")
    i.add_argument("--port")
    i.add_argument("--user")
    i.add_argument("--password")
    i.add_argument("--key-path")
    i.add_argument("--timeout")
    i.add_argument("--force", action="store_true")
    return p


SIMPLE_COMMANDS = {
    "ls": "ls -lhA {path}",
    "cat": "cat {path}",
    "ps": "ps -eo pid,user,comm,%cpu,%mem,etime --sort=-%cpu | head -15",
    "df": "df -h -x tmpfs -x devtmpfs 2>/dev/null || df -h",
    "mem": "free -h",
    "services": "systemctl list-units --type=service --state=running --no-pager 2>/dev/null "
                "| head -30 || echo '系统未使用 systemd'",
    "docker": "if command -v docker >/dev/null 2>&1; then docker ps -a "
              "--format 'table {{.Names}}\\t{{.Image}}\\t{{.Status}}\\t{{.Ports}}'; "
              "else echo '未安装 Docker'; fi",
    "ports": "ss -tulnp 2>/dev/null || netstat -tulnp 2>/dev/null || echo '缺少 ss/netstat'",
    "firewall": "if command -v ufw >/dev/null 2>&1; then ufw status verbose 2>/dev/null; "
                "elif command -v firewall-cmd >/dev/null 2>&1; then firewall-cmd --list-all 2>/dev/null; "
                "else iptables -S 2>/dev/null | head -30 || echo '无可用防火墙工具'; fi",
}


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = build_parser().parse_args(argv)
    if not args.cmd:
        build_parser().print_help()
        return 1

    if args.cmd == "init":
        return cmd_init(args)

    raw, source = load_config(args.env_file)
    c = normalize(raw)

    if args.cmd == "env":
        return cmd_env(c, source)
    if args.cmd == "doctor":
        return cmd_doctor(c, source)

    gaps = missing_required(c)
    if gaps:
        print_env_help(source, gaps)
        return 2

    if args.cmd == "info":
        return cmd_info(c)
    if args.cmd == "exec":
        return cmd_exec(c, args.command, args.json, args.timeout)
    if args.cmd == "tail":
        return cmd_tail(c, desquash_remote(args.path), args.lines)
    if args.cmd == "upload":
        return cmd_upload(c, args.local, desquash_remote(args.remote))
    if args.cmd == "download":
        return cmd_download(c, desquash_remote(args.remote), args.local)

    if args.cmd in SIMPLE_COMMANDS:
        template = SIMPLE_COMMANDS[args.cmd]
        remote_path = desquash_remote(getattr(args, "path", ""))
        command = template.replace("{path}", sh_quote(remote_path))
        client = connect(c)
        try:
            rc, out, err = run_remote(client, command)
        finally:
            client.close()
        return emit(rc, out, err)

    build_parser().print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
