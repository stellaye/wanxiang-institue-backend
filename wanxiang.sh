#!/bin/bash

# ====== 配置 ======
APP_NAME="wanxiang"
APP_DIR="/root/wanxiang-institue-backend"
MAIN_FILE="app.py"
PID_FILE="$APP_DIR/$APP_NAME.pid"
LOG_FILE="$APP_DIR/$APP_NAME.log"
PYTHON="/usr/bin/python3"  # 如果用虚拟环境，改成: /root/your_venv/bin/python

# ====== 函数 ======

start() {
    if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        echo "[$APP_NAME] 已经在运行中 (PID: $(cat $PID_FILE))"
        return 1
    fi

    echo "[$APP_NAME] 正在启动..."
    cd "$APP_DIR"
    nohup $PYTHON $MAIN_FILE >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 1

    if kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        echo "[$APP_NAME] 启动成功 (PID: $(cat $PID_FILE))"
        echo "[$APP_NAME] 日志文件: $LOG_FILE"
    else
        echo "[$APP_NAME] 启动失败，请查看日志: $LOG_FILE"
        rm -f "$PID_FILE"
        return 1
    fi
}

stop() {
    if [ ! -f "$PID_FILE" ]; then
        echo "[$APP_NAME] 未运行 (PID文件不存在)"
        return 1
    fi

    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "[$APP_NAME] 正在停止 (PID: $PID)..."
        kill "$PID"
        sleep 2

        # 如果还没停，强制杀
        if kill -0 "$PID" 2>/dev/null; then
            echo "[$APP_NAME] 强制停止..."
            kill -9 "$PID"
            sleep 1
        fi

        echo "[$APP_NAME] 已停止"
    else
        echo "[$APP_NAME] 进程不存在，清理PID文件"
    fi

    rm -f "$PID_FILE"
}

restart() {
    echo "[$APP_NAME] 正在重启..."
    stop
    sleep 1
    start
}

status() {
    if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        echo "[$APP_NAME] 运行中 (PID: $(cat $PID_FILE))"
    else
        echo "[$APP_NAME] 未运行"
        rm -f "$PID_FILE" 2>/dev/null
    fi
}

log() {
    if [ -f "$LOG_FILE" ]; then
        tail -f "$LOG_FILE"
    else
        echo "[$APP_NAME] 日志文件不存在"
    fi
}

# ====== 入口 ======

case "$1" in
    start)   start   ;;
    stop)    stop    ;;
    restart) restart ;;
    status)  status  ;;
    log)     log     ;;
    *)
        echo "用法: $0 {start|stop|restart|status|log}"
        echo ""
        echo "  start   - 启动服务"
        echo "  stop    - 停止服务"
        echo "  restart - 重启服务"
        echo "  status  - 查看状态"
        echo "  log     - 实时查看日志"
        exit 1
        ;;
esac