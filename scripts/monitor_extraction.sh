#!/bin/bash
# 监控提取脚本进度

echo "=========================================="
echo "ESG提取进度监控"
echo "=========================================="
echo ""

# 检查进程状态
if ps -p 61984 > /dev/null 2>&1; then
    echo "✅ 提取进程运行中 (PID: 61984)"
    ps -p 61984 -o etime,pcpu,rss,command | tail -1
    echo ""
else
    echo "⚠️  提取进程已结束"
    echo ""
fi

# 检查日志文件
if [ -f "extraction_run_20260806_224758.log" ]; then
    log_size=$(wc -l < extraction_run_20260806_224758.log 2>/dev/null || echo "0")
    echo "📄 日志文件行数: $log_size"
    if [ "$log_size" -gt 0 ]; then
        echo ""
        echo "最新10行日志:"
        echo "------------------------------------------"
        tail -10 extraction_run_20260806_224758.log
    else
        echo "   (日志文件为空，可能还在缓冲中)"
    fi
else
    echo "📄 日志文件未找到"
fi

echo ""
echo "=========================================="

# 检查输出文件
if [ -f "output/audit/ci_incremental_candidates_v1_2025.csv" ]; then
    old_lines=$(wc -l < output/audit/ci_incremental_candidates_v1_2025.csv)
    old_time=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M:%S" output/audit/ci_incremental_candidates_v1_2025.csv)
    echo "📊 输出文件状态:"
    echo "   行数: $old_lines"
    echo "   最后修改: $old_time"

    if ps -p 61984 > /dev/null 2>&1; then
        echo ""
        echo "💡 提示: 进程仍在运行，输出文件会在处理完成后更新"
    fi
else
    echo "📊 输出文件未找到"
fi

echo ""
echo "=========================================="
echo "当前时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="
