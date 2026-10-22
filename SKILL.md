---
name: tencent-lighthouse
description: 通过 SSH 读取、巡检和运维腾讯云轻量应用服务器（Lighthouse）。首次使用会引导创建 .env 配置模板（IP、用户名、密码），随后可查看系统概览、执行远程命令、读取日志、查看磁盘/内存/进程/端口/Docker 状态以及上传下载文件。当用户提到腾讯云轻量服务器、Lighthouse、远程登录服务器、查看服务器状态或在其上跑命令时使用。
agent_created: true
---

# 腾讯云轻量应用服务器（Lighthouse）

用 SSH 读取一台腾讯云轻量应用服务器：配置放在 `.env`，凭据不入库，脚本走 paramiko。

## 首次使用：必须完成环境配置

技能无法在缺少凭据时工作。**每次收到与服务器相关的请求，先检查配置是否就绪**：

```bash
python scripts/lh.py env      # 查看当前配置（密码已脱敏）
```

若返回「未找到可用的服务器配置」或提示缺失字段，按以下流程处理，**不要跳过、不要编造 IP**：

1. 向用户展示配置模板，并说明三项必填：

   | 变量 | 含义 | 从哪里获取 |
   | --- | --- | --- |
   | `LH_HOST` | 公网 IP | 控制台 → 轻量应用服务器 → 实例列表 |
   | `LH_USER` | 登录用户 | Ubuntu 镜像填 `ubuntu`，其余多数填 `root` |
   | `LH_PASSWORD` | 登录密码 | 控制台「重置密码」；用密钥则填 `LH_KEY_PATH` |

2. 请用户提供这三个值，然后写入配置（任选其一）：
   - 用 Write 工具创建 `<skill>/.env`（内容参照 `.env.example`，去掉注释行亦可）；
   - 或执行 `python scripts/lh.py init --host <IP> --user <用户名> --password <密码>`。

3. 验证：`python scripts/lh.py doctor` —— 依次检查配置、paramiko 依赖、TCP 端口连通性、SSH 登录，通过后再执行用户真正要的操作。

4. 若用户还没有服务器或暂时不想配置，只输出模板和获取路径，不要反复追问。

安全约定：`.env` 只写在本地，已在 `.gitignore` 中；**任何情况下不要把真实密码写进 `.env.example`、README 或提交到 Git**。输出配置时用 `env` 命令而非 `cat .env`，避免密码回显。

## 依赖

```bash
python -m pip install -r scripts/requirements.txt
```

`doctor` 会检测 paramiko 是否缺失并给出安装命令。

## 常用命令

| 目的 | 命令 |
| --- | --- |
| 配置体检（先跑） | `python scripts/lh.py doctor` |
| 查看生效配置 | `python scripts/lh.py env` |
| 主机概览 | `python scripts/lh.py info` |
| 执行任意命令 | `python scripts/lh.py exec "df -h"` |
| 结构化输出 | `python scripts/lh.py exec "uptime" --json` |
| 列目录 / 读文件 | `python scripts/lh.py ls /var/log` / `python scripts/lh.py cat /etc/os-release` |
| 看日志尾部 | `python scripts/lh.py tail /var/log/nginx/error.log -n 100` |
| 进程 / 磁盘 / 内存 | `python scripts/lh.py ps` / `df` / `mem` |
| 服务 / 端口 / 防火墙 | `python scripts/lh.py services` / `ports` / `firewall` |
| 容器状态 | `python scripts/lh.py docker` |
| 传文件 | `python scripts/lh.py upload ./a.txt /root/a.txt` / `download /root/a.log ./a.log` |

`--env-file <path>` 可指定其他配置文件；环境变量 `LH_*` 优先于文件。

## 工作方式

1. 先 `env` 判断配置，缺失则按「首次使用」引导；已配置则直接执行任务。
2. 巡检类问题（"服务器怎么样""磁盘满了吗"）优先 `info`，再按需补充 `df` / `mem` / `ps` / `docker`。
3. 需要多条命令时，合并成一条 `exec`，减少连接次数，例如 `python scripts/lh.py exec "systemctl status nginx; systemctl status mysql"`。
4. 用中文汇总结果：先给结论（正常/异常），再列关键数据，不要直接甩原始日志。
5. 涉及重启、删除、改配置等写操作时，先说明将要执行的命令与影响，得到用户确认后再执行。

## 常见故障

| 现象 | 处理 |
| --- | --- |
| 连接超时 | 实例是否开机；控制台防火墙与安全组是否放通 SSH 端口 |
| `Authentication failed` | 用户名与镜像不匹配，或密码错误（控制台重置后重试） |
| `No module named paramiko` | `python -m pip install -r scripts/requirements.txt` |
| Windows 中文乱码 | 脚本已强制 UTF-8 输出；若仍乱码，在命令前加 `chcp 65001` |
| 私钥登录报格式错误 | 私钥需为 OpenSSH 格式；PuTTY 的 `.ppk` 需先转换 |

更多环境配置细节见 `references/env-setup.md`。
