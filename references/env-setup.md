# 环境配置说明

## 1. 获取三项信息

登录腾讯云控制台 → 轻量应用服务器 Lighthouse → 实例列表，点击目标实例：

- **LH_HOST**：实例详情页的「公网 IP」。若做了内网互通，也可填内网 IP，但本机需与服务器网络可达。
- **LH_USER**：由镜像决定。
  - `Ubuntu` 镜像：默认用户 `ubuntu`（Ubuntu 系统默认禁用 root 密码登录）
  - `Debian` / `CentOS` / `宝塔面板` / `Docker` 等镜像：`root`
  - 不确定时先试 `root`，报 `Authentication failed` 再换 `ubuntu`
- **LH_PASSWORD**：实例详情页「重置密码」（或「登录」→ 重置密码）设置，重启后生效。

## 2. 放通 SSH 端口

轻量服务器有两层：

1. 实例「防火墙」（Lighthouse 自己的防火墙规则）
2. 若挂载了私有网络安全组，还需检查安全组入站规则

默认需允许 TCP `22`。若改过 SSH 端口，同步修改 `LH_PORT`。

## 3. 生成 .env

```bash
cp .env.example .env
```

或让脚本生成（写入后自动设权限 600）：

```bash
python scripts/lh.py init --host 123.45.67.89 --user root --password '你的密码'
```

验证：

```bash
python scripts/lh.py doctor
```

`doctor` 依次输出：配置来源 → 依赖版本 → TCP 连通性 → SSH 登录与 `whoami/hostname/uname`。

## 4. 用密钥代替密码（推荐）

1. 本地生成密钥（若还没有）：`ssh-keygen -t ed25519 -C lighthouse`
2. 控制台 → 实例 → 密钥对 → 绑定密钥（会重启实例）
3. `.env` 中设置 `LH_KEY_PATH=E:/keys/lighthouse`（OpenSSH 私钥，PuTTY 的 `.ppk` 不适用）
4. `LH_PASSWORD` 可留空

## 5. 配置优先级

命令行 `--env-file` > 环境变量 `LH_*` > `.env`（依次查找「skill 目录/.env」→「当前目录/.env」）。

多台服务器可维护多个 env 文件：

```bash
python scripts/lh.py --env-file E:/env/prod.env info
```

## 6. 常见报错对照

| 报错 | 原因 | 处理 |
| --- | --- | --- |
| `timed out` / `Connection refused` | 端口未放通或实例关机 | 检查实例状态与防火墙 |
| `Authentication failed` | 用户名/密码错 | 重置密码；Ubuntu 试 `ubuntu` |
| `Unable to connect to port 22` | SSH 服务异常 | 控制台 VNC 登录后 `systemctl status sshd` |
| `paramiko` 缺失 | 未装依赖 | `python -m pip install -r scripts/requirements.txt` |
| 中文乱码 | 控制台编码 | 脚本已强制 UTF-8；终端可 `chcp 65001` |

## 7. 安全建议

- `.env` 已列入 `.gitignore`，不要提交；也不要把密码粘贴进 issue、README、`.env.example`。
- 长期使用建议改 SSH 端口 + 禁用密码登录 + 仅用密钥。
- 定期在控制台轮换密码；怀疑泄露时立即重置。
- 本工具默认只做读取与巡检，写操作由调用方明确确认后执行。
