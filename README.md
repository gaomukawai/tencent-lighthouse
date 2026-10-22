# 腾讯云轻量应用服务器 Skill（tencent-lighthouse）

一个可直接安装到 WorkBuddy / 本地使用的 **Agent Skill**：通过 SSH 读取和巡检腾讯云轻量应用服务器（Lighthouse），并把连接凭据收在本地 `.env`，不写进代码、不进版本库。

## 功能

- **首次使用引导**：检测到缺少配置时，自动展示 `.env` 模板并提示填写 `IP / 用户名 / 密码`
- **配置体检** `doctor`：一次性检查配置、paramiko 依赖、TCP 端口连通性、SSH 登录
- **主机概览** `info`：系统版本、内核、运行时长、负载、CPU、内存、磁盘、内网 IP、高占用进程、最近登录
- **命令执行** `exec`：在服务器上跑任意命令，支持 `--json` 结构化输出
- **只读巡检**：`ls` / `cat` / `tail` / `ps` / `df` / `mem` / `services` / `ports` / `firewall` / `docker`
- **文件传输**：`upload` / `download`（基于 SFTP）
- **两种认证**：密码 或 OpenSSH 私钥

## 目录结构

```
tencent-lighthouse/
├── SKILL.md              # 技能定义（Agent 读取）
├── .env.example          # 配置模板（可提交）
├── .env                  # 真实凭据（本地创建，被 .gitignore 忽略）
├── scripts/
│   ├── lh.py             # 命令行实现
│   └── requirements.txt  # paramiko
└── references/
    └── env-setup.md      # 环境配置与故障排查详解
```

## 快速开始

### 1. 安装依赖

```bash
python -m pip install -r scripts/requirements.txt
```

### 2. 生成并填写 `.env`

```bash
cp .env.example .env
```

编辑 `.env`：

```ini
LH_HOST=123.45.67.89   # 控制台 → 轻量应用服务器 → 实例列表 → 公网 IP
LH_PORT=22
LH_USER=root           # Ubuntu 镜像填 ubuntu
LH_PASSWORD=你的密码    # 用密钥登录时留空
LH_KEY_PATH=           # 可选，OpenSSH 私钥路径
LH_TIMEOUT=15
```

也可以用一条命令生成：

```bash
python scripts/lh.py init --host 123.45.67.89 --user root --password '你的密码'
```

### 3. 验证

```bash
python scripts/lh.py doctor
```

输出依次为：配置来源 → paramiko 版本 → TCP 连通性 → SSH 登录信息。全部通过即可使用。

## 命令一览

```bash
python scripts/lh.py env                    # 当前配置（密码脱敏）
python scripts/lh.py info                   # 主机概览
python scripts/lh.py exec "uptime"          # 执行命令
python scripts/lh.py exec "df -h" --json    # JSON 输出
python scripts/lh.py ls /var/log            # 列目录
python scripts/lh.py cat /etc/os-release    # 读文件
python scripts/lh.py tail /var/log/nginx/error.log -n 100
python scripts/lh.py ps | df | mem          # 进程 / 磁盘 / 内存
python scripts/lh.py services | ports | firewall | docker
python scripts/lh.py upload ./app.tar.gz /root/app.tar.gz
python scripts/lh.py download /root/app.log ./app.log
```

指定其他配置文件：`python scripts/lh.py --env-file ./prod.env info`

## 作为 WorkBuddy Skill 安装

把整个目录放到用户级技能目录：

```bash
git clone <this-repo> ~/.workbuddy/skills/tencent-lighthouse
```

Windows：`%USERPROFILE%\.workbuddy\skills\tencent-lighthouse`

之后直接说「看下我腾讯云轻量服务器的情况」，技能会自动检查 `.env`，缺配置时提示你填写 IP、用户名、密码。

## 安全说明

- `.env` 已在 `.gitignore` 中，**不会**被提交；`.env.example` 只放占位值。
- `env` 命令输出密码时统一脱敏为 `******`。
- 连接默认使用 `AutoAddPolicy`（首次连接自动接受主机指纹），在内网或可信环境使用；对主机指纹有严格要求时可改为预置 `known_hosts`。
- 建议长期使用密钥登录并关闭密码登录，定期在控制台轮换密码。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 连接超时 | 实例是否开机；防火墙/安全组是否放通 22 端口 |
| `Authentication failed` | 用户名与镜像不匹配，或密码错误（控制台重置） |
| `No module named paramiko` | `python -m pip install -r scripts/requirements.txt` |
| 中文乱码 | 脚本已强制 UTF-8；终端执行 `chcp 65001` |

详见 [references/env-setup.md](references/env-setup.md)。

## License

MIT
