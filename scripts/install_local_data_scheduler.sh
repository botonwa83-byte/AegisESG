#!/usr/bin/env bash
set -eu

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
python_bin="${AEGIS_PYTHON_BIN:-$(command -v python3)}"
agent_dir="$HOME/Library/LaunchAgents"
plist="$agent_dir/com.aegisesp.data-collection.plist"
target_user="${SUDO_USER:-$(stat -f '%Su' "$repo_root")}"
target_uid="$(id -u "$target_user")"
if [ "$target_user" != "$(id -un)" ]; then
  agent_dir="/Users/$target_user/Library/LaunchAgents"
  plist="$agent_dir/com.aegisesp.data-collection.plist"
fi
mkdir -p "$agent_dir"
cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.aegisesp.data-collection</string>
  <key>ProgramArguments</key><array><string>$repo_root/scripts/run_local_data_scheduler.sh</string></array>
  <key>WorkingDirectory</key><string>$repo_root</string>
  <key>EnvironmentVariables</key><dict><key>AEGIS_PYTHON_BIN</key><string>$python_bin</string></dict>
  <key>StartInterval</key><integer>600</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$repo_root/var/local-data-collection/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$repo_root/var/local-data-collection/launchd.err.log</string>
</dict></plist>
EOF
chown "$target_user":staff "$plist" 2>/dev/null || true
launchctl bootout "gui/$target_uid/com.aegisesp.data-collection" 2>/dev/null || true
launchctl bootstrap "gui/$target_uid" "$plist"
launchctl enable "gui/$target_uid/com.aegisesp.data-collection"
launchctl kickstart -k "gui/$target_uid/com.aegisesp.data-collection"
echo "installed $plist; interval=600s; logs=$repo_root/var/local-data-collection/scheduler.log"
