#!/usr/bin/env bash
set -eu

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
python_bin="${AEGIS_PYTHON_BIN:-$(command -v python3)}"
agent_dir="$HOME/Library/LaunchAgents"
target_user="${SUDO_USER:-$(stat -f '%Su' "$repo_root")}"
target_uid="$(id -u "$target_user")"
if [ "$target_user" != "$(id -un)" ]; then
  agent_dir="/Users/$target_user/Library/LaunchAgents"
fi
mkdir -p "$agent_dir" "$repo_root/var/local-data-collection"
chmod +x "$repo_root/scripts/run_local_data_scheduler.sh" "$repo_root/scripts/run_local_text_scheduler.sh"

install_agent() {
  local label="$1"
  local script="$2"
  local interval="$3"
  local out_log="$4"
  local err_log="$5"
  local plist="$agent_dir/$label.plist"
  cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array><string>$script</string></array>
  <key>WorkingDirectory</key><string>$repo_root</string>
  <key>EnvironmentVariables</key><dict><key>AEGIS_PYTHON_BIN</key><string>$python_bin</string></dict>
  <key>StartInterval</key><integer>$interval</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$out_log</string>
  <key>StandardErrorPath</key><string>$err_log</string>
</dict></plist>
EOF
  chown "$target_user":staff "$plist" 2>/dev/null || true
  launchctl bootout "gui/$target_uid/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$target_uid" "$plist"
  launchctl enable "gui/$target_uid/$label"
  launchctl kickstart -k "gui/$target_uid/$label"
  echo "installed $plist; interval=${interval}s"
}

install_agent \
  "com.aegisesp.data-collection" \
  "$repo_root/scripts/run_local_data_scheduler.sh" \
  600 \
  "$repo_root/var/local-data-collection/launchd.out.log" \
  "$repo_root/var/local-data-collection/launchd.err.log"

install_agent \
  "com.aegisesp.text-extraction" \
  "$repo_root/scripts/run_local_text_scheduler.sh" \
  600 \
  "$repo_root/var/local-data-collection/text-launchd.out.log" \
  "$repo_root/var/local-data-collection/text-launchd.err.log"

echo "collection log=$repo_root/var/local-data-collection/scheduler.log"
echo "text log=$repo_root/var/local-data-collection/text-extraction.log"
