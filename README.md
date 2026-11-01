# Codex Quota

在 GNOME 顶栏显示 Codex **每周剩余额度**，每 60 秒更新。随桌面启动，在日期左侧保留图标，无数据时显示 `Codex ~%`，取得数据后更新。日期保持居中。

启动后立即查询，前 60 秒每 2 秒重试（单次查询最多等待 2 秒）；取得有效额度后立即恢复每 60 秒查询，超出启动窗口也恢复该频率。

需要 GNOME Shell 50、Python 3.11+、dbus-python，以及已登录的 Codex CLI。

## 安装

```sh
git clone https://github.com/wenbo-wei/codex-quota.git ~/Applications/codex-quota
cd ~/Applications/codex-quota
python3 install.py
```

注销并重新登录后生效，后台服务随桌面启动。

## 卸载

```sh
python3 install.py --uninstall
```

代码检查：`make check`。许可证：MIT。
