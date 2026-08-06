# GitHub Actions 使用说明

## 🚀 快速开始

本项目配置了两个GitHub Actions工作流，可以在GitHub上自动运行验证和分析。

---

## 📋 工作流列表

### 1. Quick Rules Verification（快速规则验证）⚡

**文件**: `.github/workflows/verify-rules.yml`

**功能**: 
- 快速验证规则数量（不运行实际提取）
- 检查6个核心指标的规则覆盖
- 生成优化报告

**触发方式**:
1. 手动触发：在GitHub仓库页面 → Actions → Quick Rules Verification → Run workflow
2. 自动触发：推送`src/aegis_esg/extraction.py`到main分支

**运行时间**: ~1分钟

**适用场景**: 
- ✅ 快速验证规则优化是否成功
- ✅ Demo前确认规则数量
- ✅ 不需要实际运行提取

---

### 2. ESG Data Extraction（完整数据提取）🔄

**文件**: `.github/workflows/extraction.yml`

**功能**:
- 运行完整的数据提取流程
- 分析提取结果
- 生成统计报告

**触发方式**:
1. 手动触发：在GitHub仓库页面 → Actions → ESG Data Extraction → Run workflow
2. 自动触发：推送相关文件到main分支

**运行时间**: ~30-120分钟（取决于PDF数量）

**适用场景**:
- ✅ 需要实际提取结果
- ✅ 验证优化效果
- ⚠️ 需要数据文件已上传到仓库

---

## 🔧 使用步骤

### 方案1: 仅验证规则（推荐用于Demo）

1. 推送代码到GitHub:
   ```bash
   git add .
   git commit -m "feat: optimize 6 core indicators with 118 rules"
   git push origin main
   ```

2. 在GitHub上查看自动运行结果:
   - 访问: https://github.com/YOUR_USERNAME/aegisESG/actions
   - 查看"Quick Rules Verification"工作流
   - 点击最新的运行记录查看结果

3. 或者手动触发:
   - Actions → Quick Rules Verification
   - 点击"Run workflow" → "Run workflow"

### 方案2: 运行完整提取（需要数据文件）

**前提条件**:
- PDF文件已上传到`data/raw/ci_collection/`
- 或修改工作流添加数据下载步骤

**步骤**:
1. 上传数据文件到GitHub（如果文件较大，考虑使用Git LFS）
2. 手动触发"ESG Data Extraction"工作流
3. 等待完成（可能需要1-2小时）
4. 下载结果artifacts

---

## 📊 查看结果

### 在GitHub Actions Summary中查看

每次运行完成后，会在Summary中显示:
- 规则统计
- 核心指标验证结果
- 优化完成状态

### 下载Artifacts

运行完成后可以下载:
- `rule-verification.txt` - 规则验证报告
- `extraction-results` - 提取结果CSV和日志（完整提取才有）

---

## 💡 关机前的操作建议

### 如果本地提取还在运行:

**选项1: 等待完成（推荐）**
```bash
# 查看进程状态
ps aux | grep 67250

# 等待完成后查看结果
python3 analyze_extraction_simple.py
```

**选项2: 保存进度并关机**
```bash
# 提取脚本会在完成时自动保存结果到CSV
# 关机前确认输出文件存在
ls -lh output/audit/ci_incremental_candidates_v1_2025.csv

# 明天可以直接分析这个文件
```

**选项3: 使用GitHub Actions重新运行**
```bash
# 1. 推送代码到GitHub
git add .
git commit -m "feat: optimize core indicators"
git push origin main

# 2. 在GitHub上手动触发提取工作流
# 3. 明天查看结果
```

---

## 🎯 明天Demo前的检查清单

### 在GitHub上验证（推荐）:
- [ ] 推送代码到GitHub
- [ ] 运行"Quick Rules Verification"工作流
- [ ] 确认118条规则部署成功
- [ ] 确认6个核心指标各有4条规则
- [ ] 截图Summary页面用于Demo

### 本地验证:
```bash
# 1. 验证规则数量
python3 test_extraction_quick.py

# 2. 分析提取结果（如果完成）
python3 analyze_extraction_simple.py

# 3. 检查核心指标覆盖率
# 对比output/audit/ci_incremental_candidates_v1_2025.csv
```

---

## 📞 故障排查

### 问题1: GitHub Actions失败

**检查**:
- Python语法错误 → 查看工作流日志
- 依赖缺失 → 检查是否需要添加requirements.txt
- 文件路径错误 → 确认文件结构

### 问题2: 本地进程卡住

**解决**:
```bash
# 检查进程状态
ps aux | grep python3 | grep extraction

# 查看日志
tail -f extraction_*.log

# 如果确实卡住，可以停止
kill <PID>
```

### 问题3: 数据文件太大无法上传GitHub

**解决方案**:
- 使用Git LFS存储大文件
- 或在工作流中添加数据下载步骤
- 或仅使用本地运行，GitHub仅做规则验证

---

## 🎉 优化成果

### 当前状态:
- ✅ 118条规则已部署
- ✅ 6个核心指标各4条规则
- ✅ 关键词新增36个
- ✅ GitHub Actions工作流配置完成
- 🔄 本地提取运行中（PID: 67250）

### 明天Demo:
- 使用GitHub Actions验证报告
- 展示规则优化成果
- 如果本地提取完成，展示实际效果

---

**祝Demo成功！** 🚀

如有问题，查看`.github/workflows/`目录下的YAML文件。
