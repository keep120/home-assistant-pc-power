# PC Power（WoL + SSH）

> 仓库：https://github.com/keep120/home-assistant-pc-power

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
5. 装 OpenSSH Server（管理员 PowerShell）：

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic
New-NetFirewallRule -Name sshd -DisplayName "OpenSSH Server" -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
```

6. 用于关机的是**本地管理员账号**，用户名不要带 `域\` 或 `微软账户邮箱`，建议单独建一个 `pc` 账号并加入 Administrators。

**Linux**

```bash
sudo systemctl enable --now ssh
echo 'hass ALL=(ALL) NOPASSWD: /usr/bin/systemctl poweroff' | sudo tee /etc/sudoers.d/hass-poweroff
```

（用户名按实际 SSH 账号改；若用私钥认证，私钥放在 `/config/.ssh/id_ed25519`，权限 600。）

## 六、排错

| 现象 | 原因 / 处理 |
|---|---|
| 点开机没反应 | 电脑没开 WoL；没关快速启动；HA 不在同一网段；Docker 部署需要 `network_mode: host` |
| 图块点了立刻变回关 | 把「开机宽限期」调大（如 180 秒） |
| 一直是“关”但电脑明明开着 | Windows 防火墙拦 ICMP 且 `445/3389/22` 都没开。开一个 SMB 或 RDP，或把备用端口改成实际开放的端口 |
| 点关机报「SSH 连接失败」 | sshd 没启动/没设开机自启；用户名不对；22 端口没放行 |
| 点关机没报错但没关 | 账号不是管理员；或被 UAC 拦。用 `shutdown /s /f /t 0` 且账号在 Administrators 组 |
| HomeKit 里没有图块 | 桥接没选这个实体；或者 iPhone 与 HA 不在同一网络、没有家庭中枢（HomePod / Apple TV） |

## 七、已知取舍

- 状态是轮询的（默认 15 秒），不是推送：关机后最多 15 秒图块才变色。
- SSH 连接不校验主机指纹（`known_hosts=None`），适合纯局域网；不要把 22 端口暴露到公网。
- SSH 密码以明文保存在 Home Assistant 的配置条目里，介意的话用私钥认证。
