# PC Power（WoL + SSH）

一个 Home Assistant 自定义集成：**每台电脑只生成一个开关实体**，开=网络唤醒、关=SSH 关机、状态=实时探测。全部在图形界面里配置，不需要写 YAML。

- 多台电脑：每台添加一次，各自一个设备 + 一个开关
- 开关同时就是状态显示：开着=开机，关着=关机（关机时实体仍然可用，不会变成“不可用”）
- 点“开”后有宽限期（默认 120 秒），家庭 App 里的图块不会点完就弹回去
- 状态探测：先 ICMP（icmplib），再 ping 命令，最后 TCP 端口兜底，Windows 防火墙拦 ping 也能用
- 关机：SSH 执行系统命令（Windows / Linux / 自定义）

## 一、安装

1. 把 `custom_components/pc_power` 整个文件夹放到 Home Assistant 的 `/config/custom_components/` 下（最终路径是 `/config/custom_components/pc_power/manifest.json`）。
   - 用 Samba / File editor / SSH 都可以，解压 `pc_power.zip` 到 `/config` 即可。
2. 重启 Home Assistant（设置 → 系统 → 右上角电源 → 重启系统）。
3. 设置 → 设备与服务 → 右下角「+ 添加集成」→ 搜索 **PC Power**。

以后想升级：替换文件夹再重启，配置不会丢。

## 二、添加一台电脑

添加集成时是两步表单。

**第一步：电脑信息**

| 字段 | 说明 |
|---|---|
| 名称 | 显示在家庭 App 上的名字，如「书房电脑」 |
| IP 地址 | 建议在路由器里给电脑做 DHCP 静态绑定 |
| MAC 地址 | `00:11:22:33:44:55`、`00-11-22-33-44-55`、`001122334455` 都认 |
| 广播地址 | 默认 `255.255.255.255`；有 VLAN / 多网段时填该网段广播地址，如 `192.168.1.255` |
| 状态刷新间隔 | 默认 15 秒，范围 5–300 |
| 开机宽限期 | 默认 120 秒；点开机后这段时间内开关保持“开” |
| 备用检测端口 | 默认 `445,3389,22`；ping 不通时用这些端口判断是否开机，留空则只用 ping |

> 集成会自动往「填的广播地址」「IP 所在网段的 .255」「255.255.255.255」都发一遍幻数据包，提高成功率。

**第二步：关机方式**

- 关机方式：`SSH 远程关机` 或 `只唤醒，不关机`
- 系统类型：`Windows` / `Linux` / `自定义命令`
- SSH 端口、用户名、认证方式（密码 / 私钥文件路径）
- 自定义关机命令（留空则用默认：Windows 是 `shutdown /s /f /t 0`，Linux 是 `sudo -n systemctl poweroff`）

添加完就能在「设置 → 设备与服务 → PC Power」里点「配置」随时改这些参数。

## 三、接进苹果家庭 App

1. 设置 → 设备与服务 → 「+ 添加集成」→ **HomeKit Bridge**（Home Assistant 自带，不是第三方）。
2. 名称随便填，**模式选「配件模式（Accessory）」**，包含模式选「仅包含指定实体」。
3. 在实体列表里只勾选这台电脑的开关（`switch.xxx`），其他一律不选。
4. 提交后会弹出一个配对码，用 iPhone「家庭」App → 右上角 + → 添加配件 → 扫码/输入配对码。

这样家庭 App 里就只有一个图块：点一下开机，再点一下关机，图块颜色就是真实开关机状态。

> 想在 App 里加图标名称，可以在 HomeKit Bridge 的「实体配置」里改显示名。开关类型是固定的（HomeKit 里没有“带状态的按钮”，开关就是最优解）。

## 四、想让所有电脑共用一个按钮

用 Home Assistant 自带的「群组」辅助元素，不用写配置：

1. 设置 → 设备与服务 → 辅助元素 → 创建辅助元素 → **群组** → 类型选 **开关**。
2. 把几台电脑的开关都加进去，命名「所有电脑」。
3. 再建一个 HomeKit Bridge（配件模式），只包含这个群组开关。

效果：打开 = 全部唤醒，关闭 = 全部关机，只要有一台在线就显示“开”。代价是没法单独叫醒某一台——所以建议「每台一个桥 + 一个总开关桥」并存，两种都有。

## 五、电脑端准备

**Windows**

1. BIOS：开启 `Power On by PCI-E / PCIe Wake`、关闭 `ErP / EuP`。
2. 网卡属性 → 电源管理：勾选「允许此设备唤醒计算机」「只允许幻数据包唤醒计算机」。
3. 网卡属性 → 高级：开启「Wake on Magic Packet」。
4. **控制面板 → 电源选项 → 选择电源按钮功能 → 关闭「启用快速启动」**（不关的话关机后网卡断电，永远唤不醒）。
5. 装 OpenSSH Server。**必须以管理员身份打开 PowerShell**（开始菜单搜 PowerShell → 右键「以管理员身份运行」），然后整段粘贴：

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd
if (-not (Get-NetFirewallRule -Name sshd -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name sshd -DisplayName "OpenSSH Server" `
        -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
}
Get-Service sshd
```

最后一行应该看到 `Status = Running`。以后重复执行这段也不会报错。

6. 用于关机的是**本地管理员账号**，用户名不要带 `域\` 或微软账户邮箱。如果平时用微软账户登录，建议单独建一个本地账号：

```powershell
$pw = Read-Host -AsSecureString "给 hass 账号设置密码"
New-LocalUser -Name "hass" -Password $pw -PasswordNeverExpires
Add-LocalGroupMember -Group "Administrators" -Member "hass"
```

集成里就填「用户名 `hass` + 刚才的密码」。

7. 验证：在**同网段的另一台电脑**上执行 `ssh hass@电脑的IP`，能登录进去就说明通了。不确定用户名时，在目标机上跑 `whoami`，反斜杠后面那一段就是 SSH 用户名。

**装不上 sshd 怎么办**

如果最后一步报「找不到任何服务名称为 sshd 的服务」，说明组件没装成功。先确认窗口标题栏写着「管理员」，然后跑这三条看卡在哪：

```powershell
Get-WindowsCapability -Online -Name OpenSSH.Server*
Get-Service sshd -ErrorAction SilentlyContinue
Get-Service wuauserv | Select-Object Status, StartType
```

- 第一条 `State : NotPresent` = 确实没装上；`Installed` 却仍没服务，重启电脑再看。
- `wuauserv` 不是 Running：组件需要从 Windows Update 下载，先 `Set-Service wuauserv -StartupType Manual; Start-Service wuauserv` 再重装。
- 报 `0x800f0954` / `0x8024402c`：多半是组策略把更新指向了内网 WSUS，把下面这个值改成 0 后重启更新服务再试：

```powershell
Set-ItemProperty "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU" -Name UseWUServer -Value 0
```

- 系统是精简版 / 组件被裁掉：直接用微软官方的 Win32-OpenSSH，不依赖系统组件。到 `github.com/PowerShell/Win32-OpenSSH/releases` 下载 `OpenSSH-Win64.zip`，解压到 `C:\Program Files\OpenSSH`，然后：

```powershell
cd "C:\Program Files\OpenSSH"
powershell -ExecutionPolicy Bypass -File .\Install-sshd.ps1
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd
```

**Linux**

```bash
sudo systemctl enable --now ssh
echo 'hass ALL=(ALL) NOPASSWD: /usr/bin/systemctl poweroff' | sudo tee /etc/sudoers.d/hass-poweroff
```

（用户名按实际 SSH 账号改；若用私钥认证，私钥放在 `/config/.ssh/id_ed25519`，权限 600。）

**macOS**

先说结论：**Mac 完全关机后无法被网络唤醒**。Apple Silicon（M 系列）关机时网卡整体断电，收不到幻数据包；Intel Mac 官方也只支持「从睡眠唤醒」。这是硬件设计，不是配置问题。

所以 Mac 的正确用法是**用睡眠代替关机**——集成里系统类型选「macOS（睡眠）」，点“关”执行的就是 `pmset sleepnow`，点“开”照常发幻数据包把它唤醒。

1. 开启远程登录：系统设置 → 通用 → 共享 → **远程登录**（这就是 macOS 的 SSH 服务）。
2. 开启网络唤醒：系统设置 → **能源** → 勾选「唤醒以供网络访问」（笔记本在「电池 → 选项」里）。命令行验证：

```bash
pmset -g | grep womp      # 应该是 womp 1
```

3. **必须接有线以太网**。Wi-Fi 下的唤醒由 Bonjour 睡眠代理实现，对幻数据包基本无效。
4. 保持接电源（笔记本仅靠电池时不会维持网络监听）。
5. 如果 `pmset sleepnow` 提示权限不足，改成 `sudo -n pmset sleepnow`，并在 `/etc/sudoers.d/` 里给该账号免密：

```bash
echo "$USER ALL=(ALL) NOPASSWD: /usr/bin/pmset sleepnow" | sudo tee /etc/sudoers.d/hass-sleep
```

6. 睡眠很久后唤不醒，多半是进了待机（standby，内存写盘、网卡断电）。可以关掉：

```bash
sudo pmset -a standby 0
```

## 六、排错

| 现象 | 原因 / 处理 |
|---|---|
| 点开机没反应 | 电脑没开 WoL；没关快速启动；HA 不在同一网段；Docker 部署需要 `network_mode: host` |
| 图块点了立刻变回关 | 把「开机宽限期」调大（如 180 秒） |
| 一直是“关”但电脑明明开着 | Windows 防火墙拦 ICMP 且 `445/3389/22` 都没开。开一个 SMB 或 RDP，或把备用端口改成实际开放的端口 |
| 点关机报「SSH 连接失败」 | sshd 没启动/没设开机自启；用户名不对；22 端口没放行 |
| 点关机没报错但没关 | 账号不是管理员；或被 UAC 拦。用 `shutdown /s /f /t 0` 且账号在 Administrators 组 |
| Mac 关机后点“开”没反应 | 正常现象，Mac 不支持从关机唤醒。把系统类型改成「macOS（睡眠）」，用睡眠代替关机 |
| Mac 睡眠后唤不醒 | 没用有线网卡；没勾「唤醒以供网络访问」；或已经进入 standby，执行 `sudo pmset -a standby 0` |
| HomeKit 里没有图块 | 桥接没选这个实体；或者 iPhone 与 HA 不在同一网络、没有家庭中枢（HomePod / Apple TV） |

## 七、已知取舍

- 状态是轮询的（默认 15 秒），不是推送：关机后最多 15 秒图块才变色。
- SSH 连接不校验主机指纹（`known_hosts=None`），适合纯局域网；不要把 22 端口暴露到公网。
- SSH 密码以明文保存在 Home Assistant 的配置条目里，介意的话用私钥认证。
