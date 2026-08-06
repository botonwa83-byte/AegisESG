#!/bin/bash
# 关机前保存进度脚本

echo "=========================================="
echo "ESG提取进度保存"
echo "=========================================="
echo ""

# 1. 检查提取进程
echo "1. 检查提取进程..."
if ps aux | grep "67250" | grep -v grep > /dev/null; then
    echo "   ✅ 提取进程仍在运行 (PID: 67250)"
    echo "   ⚠️  关机会中断此进程"
    echo ""
    echo "   选项："
    echo "   a) 等待完成再关机（推荐）"
    echo "   b) 停止进程，明天重新运行"
    echo "   c) 让进程继续，使用GitHub Actions"
else
    echo "   ℹ️  提取进程已完成或未运行"
fi
echo ""

# 2. 检查输出文件
echo "2. 检查输出文件..."
if [ -f "output/audit/ci_incremental_candidates_v1_2025.csv" ]; then
    file_size=$(ls -lh output/audit/ci_incremental_candidates_v1_2025.csv | awk '{print $5}')
    file_time=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M:%S" output/audit/ci_incremental_candidates_v1_2025.csv)
    line_count=$(wc -l < output/audit/ci_incremental_candidates_v1_2025.csv)

    echo "   ✅ 输出文件存在"
    echo "   文件大小: $file_size"
    echo "   修改时间: $file_time"
    echo "   记录数: $line_count 行"
else
    echo "   ⚠️  输出文件不存在"
fi
echo ""

# 3. 检查日志文件
echo "3. 检查日志文件..."
if ls extraction_*.log 1> /dev/null 2>&1; then
    latest_log=$(ls -t extraction_*.log | head -1)
    echo "   ✅ 最新日志: $latest_log"
    log_lines=$(wc -l < "$latest_log")
    echo "   日志行数: $log_lines"
    if [ "$log_lines" -gt 0 ]; then
        echo "   最后几行:"
        tail -3 "$latest_log" | sed 's/^/      /'
    fi
else
    echo "   ⚠️  未找到日志文件"
fi
echo ""

# 4. 创建进度快照
echo "4. 创建进度快照..."
snapshot_file="progress_snapshot_$(date +%Y%m%d_%H%M%S).txt"
{
    echo "ESG提取进度快照"
    echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
    echo "进程状态:"
    ps aux | grep "67250" | grep -v grep || echo "进程未运行"
    echo ""
    echo "输出文件:"
    ls -lh output/audit/ci_incremental_candidates_v1_2025.csv 2>/dev/null || echo "文件不存在"
    echo ""
    echo "规则统计:"
    python3 -c "
import sys
sys.path.insert(0, 'src')
from aegis_esg.extraction import DIRECT_RULES, RULES
print(f'DirectRule: {len(DIRECT_RULES)}条')
print(f'_rule: {len(RULES)}条')
print(f'总计: {len(DIRECT_RULES) + len(RULES)}条')
" 2>/dev/null
} > "$snapshot_file"

echo "   ✅ 快照已保存: $snapshot_file"
echo ""

# 5. Git状态
echo "5. Git状态..."
if git status > /dev/null 2>&1; then
    uncommitted=$(git status --short | wc -l)
    if [ "$uncommitted" -gt 0 ]; then
        echo "   ⚠️  有 $uncommitted 个未提交的文件"
        echo "   建议推送到GitHub保存进度："
        echo "   git add ."
        echo "   git commit -m 'feat: optimize 118 rules for core indicators'"
        echo "   git push origin main"
    else
        echo "   ✅ 所有文件已提交"
    fi
else
    echo "   ℹ️  不是Git仓库"
fi
echo ""

# 6. 明天恢复指南
echo "=========================================="
echo "明天恢复指南"
echo "=========================================="
echo ""
echo "选项1: 查看本地结果（如果提取已完成）"
echo "  python3 analyze_extraction_simple.py"
echo ""
echo "选项2: 在GitHub上验证规则"
echo "  访问: https://github.com/YOUR_USERNAME/aegisESG/actions"
echo "  运行: Quick Rules Verification"
echo ""
echo "选项3: 重新运行提取"
echo "  PYTHONPATH=src python3 scripts/run_incremental_indicator_extraction.py"
echo ""
echo "=========================================="
echo "当前时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="
