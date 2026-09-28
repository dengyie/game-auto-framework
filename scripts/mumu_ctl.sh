#!/bin/zsh
# MuMu 模拟器控制脚本 —— 从本机 Mac 跨机控制 home-win 上的 MuMu 12。
#
# 为什么启动必须走计划任务：
#   直接 `ssh home-win "mumu-cli.exe control launch"` 跑在 SSH 的 Session 0，
#   引擎进程能起来但安卓不实际 boot（2026-09-26 实踩，试了三次）。
#   必须用 schtasks /IT 在交互式桌面会话（session 1）拉起才真正开安卓；
#   配合 /RL HIGHEST 可静默提权，升级安装包不再需要手点 UAC。
#
# 升级注意（2026-09-26，4.1.33 → 5.30.1）：
#   新版把管理器移到 nx_main\mumu-cli.exe，设备引擎在 nx_device\12.0\shell\；
#   旧版是 shell\MuMuManager.exe。本脚本自动探测两者。
#   强制更新未完成时，launch 会只弹更新窗口而不启动安卓 —— 先跑 upgrade。
#
# 远端命令一律走 powershell -EncodedCommand（UTF-16LE base64）：
#   Windows 反斜杠路径经过 ssh 多层引号会被转义吞掉（2026-09-27 实踩：
#   `12\nx_main` 里的 \n 被当成换行、路径打印错乱），base64 完全绕开引号层。
# 远端 .cmd 文件按铁律用 base64 写入 + 回读校验。
#
# 用法（本机 Mac）：
#   ./mumu_ctl.sh status       实例信息 + ADB 连通性
#   ./mumu_ctl.sh start        拉起引擎与安卓，等待 ADB 就绪
#   ./mumu_ctl.sh stop         正常关机
#   ./mumu_ctl.sh restart      重启
#   ./mumu_ctl.sh upgrade <URL> 下载并静默安装官方安装包
#   ./mumu_ctl.sh launch-app   启动游戏（com.netease.my）
#
# 依赖：~/.ssh/config 的 home-win（mDNS 直连）与 home-win-tunnel（兜底）；
#      ADB 16384 由 LaunchAgent com.mango.mumu-adb-forward 固定转发。

set -u

ADB_DEV="127.0.0.1:16384"
VMINDEX=0
GAME_PKG="com.netease.my"
LAN_HOST=home-win
TUNNEL_HOST=home-win-tunnel
REMOTE_USER=mango
SSH=/usr/bin/ssh
INSTALL_ROOT='D:\Program Files\Netease\MuMu Player 12'
NEW_CLI="$INSTALL_ROOT\\nx_main\\mumu-cli.exe"
OLD_CLI="$INSTALL_ROOT\\shell\\MuMuManager.exe"

pick_host() {
  if "$SSH" -o BatchMode=yes -o ConnectTimeout=6 "$LAN_HOST" exit 2>/dev/null; then
    print -r -- "$LAN_HOST"
  else
    print -r -- "$TUNNEL_HOST"
  fi
}
HOST="$(pick_host)"

# 远端执行 PowerShell：脚本经 UTF-16LE base64 用 -EncodedCommand 传入，
# 不经过 ssh 的引号解析，路径、引号、中文都不会被改写。
ps_remote() {
  local script="$1" b64
  b64=$(printf '%s' "$script" | iconv -f UTF-8 -t UTF-16LE | base64 | tr -d '\n')
  "$SSH" -o ConnectTimeout=25 "$HOST" "powershell -NoProfile -EncodedCommand $b64"
}

# 在交互式桌面会话以最高权限执行一条命令：
# 把 payload 写成 .cmd（base64 写入 + 回读校验），schtasks /Create /Run /Delete 一条龙。
run_interactive() {
  local payload="$1"
  local tn="MuMuCtl$$"
  local p="C:\\Users\\$REMOTE_USER\\$tn.cmd"
  local b64
  b64=$(printf '%s' "$payload" | base64 | tr -d '\n')
  ps_remote "
\$tn='$tn'
\$p='$p'
\$b='$b64'
[IO.File]::WriteAllBytes(\$p, [Convert]::FromBase64String(\$b))
\$back=[IO.File]::ReadAllText(\$p)
\$exp=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(\$b))
if (\$back -ne \$exp) { Write-Output 'FILE-MISMATCH'; exit 1 }
schtasks /Create /TN \$tn /TR \$p /SC ONCE /ST 23:59 /RU $REMOTE_USER /RL HIGHEST /IT /F | Out-Null
schtasks /Run /TN \$tn | Out-Null
Start-Sleep -Seconds 3
schtasks /Delete /TN \$tn /F | Out-Null
Remove-Item \$p -Force -ErrorAction SilentlyContinue
Write-Output 'dispatched'
"
}

# 解析当前该用哪个 CLI：优先新版 nx_main\mumu-cli.exe
resolve_cli() {
  ps_remote "if (Test-Path '$NEW_CLI') { Write-Output 'new' } elseif (Test-Path '$OLD_CLI') { Write-Output 'old' } else { Write-Output 'none' }" \
    | tr -d '\r' | tr -d $'\xEF\xBB\xBF' | grep -E '^(new|old|none)$' | tail -1
}

cli_path() {
  case "$(resolve_cli)" in
    new) print -r -- "$NEW_CLI";;
    old) print -r -- "$OLD_CLI";;
    *)   print -r -- "";;
  esac
}

wait_adb() {
  local timeout="${1:-180}" waited=0
  print "→ 等待 ADB 就绪（最多 ${timeout}s）..."
  while true; do
    if adb -s "$ADB_DEV" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' | grep -q '^1$'; then
      print "  ✓ ADB online  (sys.boot_completed=1)"
      return 0
    fi
    if [ "$waited" -ge "$timeout" ]; then
      print "  ✗ 超时：ADB 仍未就绪"
      return 1
    fi
    sleep 5; waited=$((waited + 5))
  done
}

ensure_adb_tunnel() {
  adb connect "$ADB_DEV" >/dev/null 2>&1 || true
}

CMD="${1:-status}"
CLI="$(cli_path)"

case "$CMD" in
  status)
    print "== host =="; print "  $HOST"
    if [ -n "$CLI" ]; then print -r -- "== cli ==  $CLI"; else print "== cli ==  未找到 MuMu CLI"; fi
    if [ -n "$CLI" ]; then
      ps_remote "& '$CLI' info -v $VMINDEX"
    fi
    print "== adb =="
    adb devices | grep "$ADB_DEV" || print "  未连接（模拟器可能已关闭）"
    ;;

  start)
    if [ -z "$CLI" ]; then print "✗ 未找到 MuMu CLI，安装路径可能已变"; exit 1; fi
    print "→ 在交互式桌面会话拉起实例 $VMINDEX ..."
    run_interactive "\"$CLI\" control -v $VMINDEX launch"
    ensure_adb_tunnel
    wait_adb 240
    ;;

  stop)
    if [ -z "$CLI" ]; then print "✗ 未找到 MuMu CLI"; exit 1; fi
    print "→ 关机实例 $VMINDEX ..."
    run_interactive "\"$CLI\" control -v $VMINDEX shutdown"
    ;;

  restart)
    if [ -z "$CLI" ]; then print "✗ 未找到 MuMu CLI"; exit 1; fi
    print "→ 重启实例 $VMINDEX ..."
    run_interactive "\"$CLI\" control -v $VMINDEX restart"
    ensure_adb_tunnel
    wait_adb 240
    ;;

  upgrade)
    local url="${2:?用法: $0 upgrade <安装包下载URL>}"
    print "→ 下载官方安装包 ..."
    ps_remote "\$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '$url' -OutFile 'D:\\mumu-setup-tmp.exe'; (Get-Item 'D:\\mumu-setup-tmp.exe').Length"
    print "→ 以最高权限静默安装（自动提权，无需手点 UAC）..."
    run_interactive "\"D:\\mumu-setup-tmp.exe\" /S"
    print "  安装完成后重跑: $0 status / $0 start"
    ;;

  launch-app)
    ensure_adb_tunnel
    if [ -z "$CLI" ]; then print "✗ 未找到 MuMu CLI"; exit 1; fi
    print "→ 拉起游戏 $GAME_PKG ..."
    if ps_remote "& '$CLI' control -v $VMINDEX app launch --package $GAME_PKG" | grep -q '"errcode": *0'; then
      print "  ✓ 已用 MuMu CLI 启动 $GAME_PKG"
    else
      print "  CLI 拉起失败（已知 -201 问题），回退 adb am start"
      adb -s "$ADB_DEV" shell "am start -n $GAME_PKG/.ic_launcher" >/dev/null 2>&1 \
        && print "  ✓ 已用 adb 启动 $GAME_PKG" \
        || print "  ✗ 启动失败"
    fi
    ;;

  *)
    print "用法: $0 {status|start|stop|restart|upgrade <URL>|launch-app}"
    exit 2;;
esac