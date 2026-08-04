#!/bin/sh
set -eu

# 安全重启领导演示服务：停止本项目记录的旧进程，清理指定端口后后台启动。
# 不使用 sudo，避免切换到另一套 Python/uvicorn 环境。
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PORT="${AEGIS_DEMO_PORT:-8000}"
PID_FILE="$PROJECT_ROOT/var/aegis-demo.pid"
LOG_FILE="$PROJECT_ROOT/var/aegis-demo.log"
mkdir -p "$PROJECT_ROOT/var"

stop_pid() {
    pid="$1"
    case "$pid" in
        ''|*[!0-9]*) return 0 ;;
    esac
    if kill -0 "$pid" 2>/dev/null; then
        echo "停止旧 Demo 进程: $pid"
        kill "$pid" 2>/dev/null || true
        i=0
        while kill -0 "$pid" 2>/dev/null && [ "$i" -lt 20 ]; do
            sleep 0.1
            i=$((i + 1))
        done
        kill -9 "$pid" 2>/dev/null || true
    fi
}

if [ -f "$PID_FILE" ]; then
    stop_pid "$(sed -n '1p' "$PID_FILE")"
    rm -f "$PID_FILE"
fi

# 只清理指定端口的监听进程，不扫描或终止其他 uvicorn 服务。
if command -v lsof >/dev/null 2>&1; then
    for pid in $(lsof -ti "tcp:$PORT" 2>/dev/null || true); do
        stop_pid "$pid"
    done
fi

echo "启动 Demo: http://127.0.0.1:$PORT/demo"
(
    cd "$PROJECT_ROOT"
    nohup env AEGIS_DEMO_PORT="$PORT" sh "$SCRIPT_DIR/run_real_system_demo.sh" >>"$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
)

sleep 1
if [ -f "$PID_FILE" ] && kill -0 "$(sed -n '1p' "$PID_FILE")" 2>/dev/null; then
    echo "Demo 已后台启动"
    echo "日志: $LOG_FILE"
    echo "停止: kill $(sed -n '1p' "$PID_FILE")"
else
    echo "Demo 启动失败，请查看日志: $LOG_FILE" >&2
    exit 1
fi
