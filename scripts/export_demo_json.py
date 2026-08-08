#!/usr/bin/env python3
"""
生成Demo页面所需的JSON数据文件（简化版，使用标准库）
从增强数据CSV生成轻量级JSON，供前端JavaScript加载
"""

import csv
import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime
import sys

# 添加src到路径以导入methodology
sys.path.insert(0, 'src')

# 配置
INPUT_CSV = "output/research/2025/enhanced_observations_v3_industry_filled.csv"
RANKING_DIR = "output/research/2025/tiered_rankings"
OUTPUT_DIR = "public-demo/data"

def load_indicator_metadata():
    """从methodology加载指标元数据"""
    try:
        from aegis_esg.methodology import load_methodology
        method = load_methodology('data/methodologies/energy_esg_2025.json')

        # 构建指标字典
        indicator_dict = {}
        for ind in method.indicators:
            # 处理dimension可能是字符串或枚举
            dim = ind.dimension
            if hasattr(dim, 'value'):
                dim = dim.value

            indicator_dict[ind.code] = {
                'name': ind.name,
                'dimension': dim,
            }

        print(f"✓ 加载 {len(indicator_dict)} 个指标元数据")
        return indicator_dict
    except Exception as e:
        print(f"⚠️  无法加载methodology: {e}")
        print("    将从CSV数据推断指标信息")
        return {}

def load_csv_data(filepath):
    """加载CSV数据"""
    data = []
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)
    return data

def load_data():
    """加载增强观测数据"""
    print(f"📂 加载数据: {INPUT_CSV}")
    data = load_csv_data(INPUT_CSV)
    print(f"✓ 共 {len(data)} 条观测数据")
    return data

def load_rankings():
    """加载排名数据"""
    basic_path = Path(RANKING_DIR) / "basic_ranking_2025.csv"
    premium_path = Path(RANKING_DIR) / "premium_ranking_2025.csv"

    basic = load_csv_data(basic_path) if basic_path.exists() else None
    premium = load_csv_data(premium_path) if premium_path.exists() else None

    print(f"✓ 基础排名: {len(basic) if basic else 0} 家企业")
    print(f"✓ 高级排名: {len(premium) if premium else 0} 家企业")

    return basic, premium

def generate_company_list(data, basic_ranking, premium_ranking):
    """生成企业列表JSON"""
    print("\n📊 生成企业列表...")

    # 按企业聚合数据
    company_data = defaultdict(list)
    for row in data:
        code = row['company_code']
        company_data[code].append(row)

    # 构建排名字典
    basic_dict = {}
    premium_dict = {}

    if basic_ranking:
        for row in basic_ranking:
            basic_dict[row['company_code']] = {
                'rank': int(row['rank']),
                'score': float(row['total_score'])
            }

    if premium_ranking:
        for row in premium_ranking:
            premium_dict[row['company_code']] = {
                'rank': int(row['rank']),
                'score': float(row['total_score'])
            }

    # 生成企业列表
    companies = []
    for code, rows in company_data.items():
        name = rows[0]['company_name']
        industry = rows[0].get('industry', '未分类')

        # 统计数据来源
        confirmed = sum(1 for r in rows if r.get('status') == 'confirmed')
        imputed = sum(1 for r in rows if r.get('status') == 'imputed')
        total = len(rows)

        # 获取排名
        basic_info = basic_dict.get(code, {})
        premium_info = premium_dict.get(code, {})

        companies.append({
            'code': code,
            'name': name,
            'industry': industry,
            'coverage_rate': round(confirmed / total * 100, 1) if total > 0 else 0,
            'confirmed_count': confirmed,
            'imputed_count': imputed,
            'missing_count': total - confirmed - imputed,
            'total_indicators': total,
            'basic_rank': basic_info.get('rank'),
            'basic_score': round(basic_info.get('score', 0), 2) if basic_info.get('score') else None,
            'premium_rank': premium_info.get('rank'),
            'premium_score': round(premium_info.get('score', 0), 2) if premium_info.get('score') else None,
        })

    # 按高级排名排序
    companies.sort(key=lambda x: x['premium_rank'] if x['premium_rank'] else 9999)

    print(f"✓ 生成 {len(companies)} 家企业")
    return companies

def generate_company_details(data, companies_list, indicator_metadata):
    """生成企业详细数据（仅top 100）"""
    print("\n📋 生成企业详细数据...")

    # 按企业组织数据
    company_data = defaultdict(list)
    for row in data:
        company_data[row['company_code']].append(row)

    # 只生成前100家企业的详细数据
    top_companies = companies_list[:100]
    details = []

    for company in top_companies:
        code = company['code']
        rows = company_data.get(code, [])

        # 按维度组织指标
        indicators_by_dim = {'E': [], 'S': [], 'G': []}

        for row in rows:
            ind_code = row.get('indicator_code', '')

            # 从metadata获取维度和名称
            ind_meta = indicator_metadata.get(ind_code, {})
            dim = ind_meta.get('dimension', '')
            ind_name = ind_meta.get('name', ind_code)

            if dim not in indicators_by_dim:
                continue

            value = row.get('value', '')
            try:
                value = float(value) if value else None
            except:
                value = None

            confidence = row.get('confidence', '1.0')
            try:
                confidence = round(float(confidence), 2)
            except:
                confidence = 1.0

            indicators_by_dim[dim].append({
                'code': ind_code,
                'name': ind_name,
                'value': value,
                'source': row.get('status', '').lower(),
                'confidence': confidence,
            })

        details.append({
            'code': code,
            'name': company['name'],
            'industry': company['industry'],
            'coverage_rate': company['coverage_rate'],
            'confirmed_count': company['confirmed_count'],
            'imputed_count': company['imputed_count'],
            'basic_rank': company['basic_rank'],
            'basic_score': company['basic_score'],
            'premium_rank': company['premium_rank'],
            'premium_score': company['premium_score'],
            'indicators': indicators_by_dim,
        })

    print(f"✓ 生成 {len(details)} 家企业详细数据")
    return details

def generate_statistics(data, indicator_metadata):
    """生成统计数据"""
    print("\n📈 生成统计数据...")

    total_obs = len(data)
    confirmed = sum(1 for r in data if r.get('status') == 'confirmed')
    imputed = sum(1 for r in data if r.get('status') == 'imputed')

    # 按维度统计
    dim_stats = []
    for dim in ['E', 'S', 'G']:
        # 从metadata筛选该维度的指标
        dim_indicators = [code for code, meta in indicator_metadata.items() if meta.get('dimension') == dim]
        dim_data = [r for r in data if r.get('indicator_code') in dim_indicators]
        dim_confirmed = sum(1 for r in dim_data if r.get('status') == 'confirmed')
        dim_imputed = sum(1 for r in dim_data if r.get('status') == 'imputed')
        dim_total = len(dim_data)

        dim_stats.append({
            'dimension': dim,
            'name': {'E': '环境', 'S': '社会', 'G': '治理'}[dim],
            'confirmed': dim_confirmed,
            'imputed': dim_imputed,
            'total': dim_total,
            'confirmed_rate': round(dim_confirmed / dim_total * 100, 1) if dim_total > 0 else 0,
        })

    # 按指标统计（采样前20个）
    indicator_groups = defaultdict(list)
    for row in data:
        code = row.get('indicator_code', '')
        if code:
            indicator_groups[code].append(row)

    indicator_stats = []
    for code in list(indicator_groups.keys())[:20]:
        rows = indicator_groups[code]
        ind_confirmed = sum(1 for r in rows if r.get('status') == 'confirmed')
        ind_imputed = sum(1 for r in rows if r.get('status') == 'imputed')
        ind_total = len(rows)

        # 计算平均置信度
        confidences = []
        for r in rows:
            try:
                confidences.append(float(r.get('confidence', 1.0)))
            except:
                confidences.append(1.0)
        avg_conf = sum(confidences) / len(confidences) if confidences else 1.0

        # 从metadata获取名称和维度
        ind_meta = indicator_metadata.get(code, {})

        indicator_stats.append({
            'code': code,
            'name': ind_meta.get('name', code),
            'dimension': ind_meta.get('dimension', ''),
            'companies': ind_total,
            'confirmed': ind_confirmed,
            'imputed': ind_imputed,
            'imputed_rate': round(ind_imputed / ind_total * 100, 1) if ind_total > 0 else 0,
            'avg_confidence': round(avg_conf, 3),
        })

    stats = {
        'overview': {
            'total_observations': total_obs,
            'confirmed': confirmed,
            'imputed': imputed,
            'confirmed_rate': round(confirmed / total_obs * 100, 1),
            'imputed_rate': round(imputed / total_obs * 100, 1),
        },
        'by_dimension': dim_stats,
        'by_indicator': indicator_stats,
    }

    print(f"✓ 统计数据生成完成")
    return stats

def main():
    print("🚀 开始生成Demo数据...\n")

    # 创建输出目录
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 加载指标元数据
    indicator_metadata = load_indicator_metadata()

    # 加载数据
    data = load_data()
    basic_ranking, premium_ranking = load_rankings()

    # 生成各类数据
    companies_list = generate_company_list(data, basic_ranking, premium_ranking)
    company_details = generate_company_details(data, companies_list, indicator_metadata)
    statistics = generate_statistics(data, indicator_metadata)

    # 保存JSON文件
    print("\n💾 保存JSON文件...")
    timestamp = datetime.now().isoformat()

    # 1. 企业列表（完整）
    with open(output_dir / "companies.json", "w", encoding="utf-8") as f:
        json.dump({
            'metadata': {
                'total': len(companies_list),
                'generated_at': timestamp,
            },
            'companies': companies_list,
        }, f, ensure_ascii=False, indent=2)
    print(f"✓ companies.json ({len(companies_list)} 家企业)")

    # 2. 企业详细数据（top 100）
    with open(output_dir / "company-details.json", "w", encoding="utf-8") as f:
        json.dump({
            'metadata': {
                'total': len(company_details),
                'note': 'Top 100 companies with full indicator details',
                'generated_at': timestamp,
            },
            'details': company_details,
        }, f, ensure_ascii=False, indent=2)
    print(f"✓ company-details.json ({len(company_details)} 家企业)")

    # 3. 统计数据
    with open(output_dir / "statistics.json", "w", encoding="utf-8") as f:
        json.dump({
            'metadata': {
                'generated_at': timestamp,
            },
            'stats': statistics,
        }, f, ensure_ascii=False, indent=2)
    print(f"✓ statistics.json")

    # 4. 排名数据（top 100）
    if basic_ranking and premium_ranking:
        rankings = {
            'metadata': {
                'basic_total': len(basic_ranking),
                'premium_total': len(premium_ranking),
                'generated_at': timestamp,
            },
            'basic': basic_ranking[:100],
            'premium': premium_ranking[:100],
        }

        with open(output_dir / "rankings.json", "w", encoding="utf-8") as f:
            json.dump(rankings, f, ensure_ascii=False, indent=2)
        print(f"✓ rankings.json (top 100)")

    print("\n✅ Demo数据生成完成！")
    print(f"📁 输出目录: {output_dir.absolute()}")

    # 显示文件大小
    print("\n📊 文件大小:")
    for file in output_dir.glob("*.json"):
        size = file.stat().st_size
        size_kb = size / 1024
        print(f"  {file.name}: {size_kb:.1f} KB")

if __name__ == "__main__":
    main()
