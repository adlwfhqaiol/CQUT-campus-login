# 重庆理工大学校园网自动登录

一个使用 Python 标准库实现的重庆理工大学校园网自动认证脚本。支持有线网和校园 Wi-Fi，可单次登录、持续监测断线重连，并安装开机自启。

> 本项目是非官方工具，与重庆理工大学及锐捷网络无关。自动认证不会绕过学校的任何认证策略；请只使用自己的账号，并遵守学校网络管理规定。学校升级认证页后，脚本可能需要同步更新。

## 功能

- 识别锐捷 ePortal 跳转参数，自动选择服务出口
- 支持学校统一身份认证和直接 ePortal 认证
- 使用 Windows DPAPI 加密保存账号密码
- 内置固定字形验证码识别，不需要第三方 OCR 库
- `--watch` 守护模式断线重连，使用互斥锁避免重复启动
- 支持 Windows 计划任务；策略禁止时自动改用当前用户启动文件夹
- 日志自动轮转，默认只保留当前日志和一份旧日志
- 所有网络请求只使用 Python 标准库

## 环境要求

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Windows 10 / 11（安全凭据存储与开机自启目前只支持 Windows） |
| Python | 3.10 或更高版本 |
| 浏览器 | Microsoft Edge |
| Node.js | 22 或更高版本（推荐；用于无界面 Edge 完成 SSO 回跳） |

如果 Node.js 或 Edge 不可用，脚本会尝试直接调用 SSO 接口，但兼容性不如浏览器流程。

## 快速开始

```powershell
git clone <https://github.com/adlwfhqaiol/cqut-campus-login>
cd .\cqut-campus-login
py -3 .\cqut_campus_login.py --init
```

`--init` 会要求输入统一身份认证账号，并连续输入两次密码。密码输入时不显示，校验通过后才覆盖旧凭据。

立即登录一次：

```powershell
py -3 .\cqut_campus_login.py
```

持续监测并在断线后重连：

```powershell
py -3 .\cqut_campus_login.py --watch
```

也可以直接双击：

```text
启动校园网登录.cmd
```

## 开机自启

```powershell
py -3 .\cqut_campus_login.py --install-task
```

安装顺序：

1. 尝试创建当前用户的 Windows 计划任务。
2. 如果系统策略拒绝，则改用“启动”文件夹中的隐藏 VBS。
3. 计划任务创建成功后，会清理旧的启动文件夹或注册表自启项，避免重复运行。

删除自启：

```powershell
py -3 .\cqut_campus_login.py --uninstall-task
```

## 日志与诊断

查看所有本地文件位置：

```powershell
py -3 .\cqut_campus_login.py --paths
```

默认路径：

| 内容 | 路径 |
| --- | --- |
| 配置 | `%LOCALAPPDATA%\CQUTCampusLogin\settings.json` |
| 凭据 | `%LOCALAPPDATA%\CQUTCampusLogin\credentials.bin` |
| 日志 | `%LOCALAPPDATA%\CQUTCampusLogin\login.log` |
| Edge 临时配置 | `%LOCALAPPDATA%\CQUTCampusLogin\edge-profile` |

实时查看运行过程：

```powershell
Get-Content "$env:LOCALAPPDATA\CQUTCampusLogin\login.log" -Tail 50 -Wait -Encoding UTF8
```

检查网络状态：

```powershell
py -3 .\cqut_campus_login.py --check
```

检查门户、认证方式和服务出口：

```powershell
py -3 .\cqut_campus_login.py --diagnose
```

`--diagnose` 不会提交账号密码。要进入登录页诊断，请先让当前认证过期，或连接到尚未认证的校园网。

## 服务出口

默认优先选择标签中包含“移动”的服务。临时切换出口：

```powershell
py -3 .\cqut_campus_login.py --service "电信"
```

也可以在 `settings.json` 中修改 `service_keyword`，或把 `service` 设为固定服务值。

## 环境变量

环境变量适合自动化或非 Windows 环境。使用 `CQUT_USERNAME` 和 `CQUT_PASSWORD` 时，脚本不会再读取 DPAPI 凭据文件。

| 变量 | 说明 |
| --- | --- |
| `CQUT_USERNAME` | 统一身份认证账号 |
| `CQUT_PASSWORD` | 统一身份认证密码 |
| `CQUT_DATA_DIR` | 覆盖配置、日志和凭据目录 |

在 GitHub Actions 等公开 CI 中，不要把真实账号写进仓库。需要联网测试时，请使用仓库 Secrets。

## 安全说明

- Windows 上账号密码通过 DPAPI 加密，只有保存它的 Windows 用户可解密。
- 非 Windows 系统不再允许把凭据以明文形式写入 `credentials.bin`；请使用环境变量。
- 密码通过标准输入传给本机 Node.js 助手，不写入进程命令行参数。
- 日志会隐藏账号、密码和本次验证码，并压平换行，避免外部页面内容伪造日志。
- Edge 用户数据保存在本机，用于完成 SSO 跳转；不要将该目录上传或分享。
- 密码错误时脚本会停止本次自动重试，降低账号临时锁定风险。
- 发现安全问题时请通过仓库的 GitHub Security Advisory 私下报告，不要公开账号、Cookie、验证码或成功页截图。

## 已知限制

- 学校修改门户地址、SSO 接口、RSA 公钥或验证码字形后，脚本可能需要更新。
- 固定验证码识别只适配当前已采集的 80×30 四字符字形。
- `--init` 默认按重庆理工大学当前 10 位密码校验；密码规则变化时可调整配置中的 `password_length`。
- 守护模式是用户级后台进程，不等同于 Windows 服务。

## 目录结构

```text
.
├── cqut_campus_login.py      # 主脚本
├── edge_sso_login.mjs        # 无界面 Edge + CDP 登录助手
├── 启动校园网登录.cmd
├── tests/
├── .github/workflows/ci.yml
├── SECURITY.md
└── README.md
```

## 许可证

本项目使用 MIT License，详见 [LICENSE](LICENSE)。
