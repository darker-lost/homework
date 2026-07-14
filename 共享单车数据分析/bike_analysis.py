# -*- coding: utf-8 -*-
"""
共享单车数据分析及可视化
==========================

本脚本读取 Excel 数据后，依次完成 4 项分析任务：
1. 统计全月每日单车使用量，绘制柱状图
2. 分析周一至周日全天 24 小时用车分布规律，绘制折线图
3. 分析工作日、周末不同时段的用车差异，绘制折线图
4. 统计不同骑行距离的订单占比，绘制饼图

所有分析结果（CSV 数据 + PNG 图表）默认输出到 bike_analysis_output/ 目录。
"""

import os
from typing import List, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# ============================================================
# 第 1 部分：全局配置常量
# ============================================================
# 使用全大写命名约定，表示这些值是“配置项”，方便后续修改。

# 脚本所在目录，确保数据文件路径不受运行目录影响
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 输入文件路径（使用脚本所在目录作为基准）
DATA_FILE = os.path.join(SCRIPT_DIR, '共享单车数据(1).xlsx')
SHEET_NAME = 'train1'

# 输出目录
OUTPUT_DIR = 'bike_analysis_output'

# 图表通用样式参数
FIG_DPI = 200                 # 图片分辨率，越高越清晰，文件也越大
DEFAULT_FIGSIZE = (12, 6)     # 默认图表尺寸（宽, 高），单位英寸

# 距离分段规则：左闭右开 [0,1), [1,2), [2,3), [3,5), [5, +∞)
# 共享单车的短距离订单占主体，所以 0-1km、1-2km 的区间较细。
DISTANCE_BINS: List[float] = [0, 1, 2, 3, 5, np.inf]
DISTANCE_LABELS: List[str] = ['0-1km', '1-2km', '2-3km', '3-5km', '>5km']

# 星期映射：pandas 的 dayofweek 返回 0~6，0 代表周一。
WEEKDAY_NAMES: List[str] = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
WEEKDAY_MAP: dict[int, str] = {i: name for i, name in enumerate(WEEKDAY_NAMES)}

# 工作日/周末映射：原始数据 weekend 字段，0=工作日，1=周末。
DAY_TYPE_MAP: dict[int, str] = {0: '工作日', 1: '周末'}


# ============================================================
# 第 2 部分：环境初始化函数
# ============================================================

def ensure_output_dir(output_dir: str = OUTPUT_DIR) -> str:
    """
    确保输出目录存在。

    注意：目录创建放在函数里，而不是模块导入时执行。
    这样别人 import 本脚本时不会立即在磁盘上创建目录，更友好。
    """
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def set_chinese_font() -> None:
    """
    设置 Matplotlib 中文字体。

    Windows 通常自带 SimHei（黑体），所以优先使用；
    如果找不到，matplotlib 会回退到默认字体，可能出现中文乱码。
    这里给了一个 fallback 列表，提高在不同机器上的兼容性。
    """
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
    # 解决负号显示为方块的问题
    plt.rcParams['axes.unicode_minus'] = False


# ============================================================
# 第 3 部分：数据读取与清洗
# ============================================================

def find_distance_column(df: pd.DataFrame) -> str:
    """
    自动定位“骑行距离”列。

    原始 Excel 中该列的列名可能因编码问题显示异常，不能简单地按名称匹配。
    定位策略：
    1. 先排除所有“肯定不是距离”的列（ID、序号、坐标、时间拆分字段等）。
    2. 在剩余的数值列中，优先选择最右边的那一列。
       因为本数据集里骑行距离正好是最后一列，这样最稳健。
    3. 如果没有剩余候选列，则退化为最后一列作为兜底。

    参数:
        df: 原始 DataFrame
    返回:
        距离列的列名字符串
    """
    # 已知的非距离字段集合
    non_distance_cols = {
        # 索引/ID 类
        'Unnamed: 0', 'orderid', 'bikeid', 'userid',
        # 坐标类
        'start_location_x', 'start_location_y',
        'end_location_x', 'end_location_y',
        # 时间拆分字段
        'start_year', 'start_month', 'start_day', 'start_hour',
        # 其他类别字段
        'weekend'
    }

    # 所有数值型列
    numeric_cols = df.select_dtypes(include=['number']).columns.tolist()

    # 候选列：数值型且不在非距离集合中
    candidates = [col for col in numeric_cols if col not in non_distance_cols]

    if candidates:
        # 优先取最右边的候选列（本数据集中距离列在最后）
        return candidates[-1]

    # 兜底：返回最后一列
    return df.columns[-1]


def load_data(file_path: str = DATA_FILE, sheet_name: str = SHEET_NAME) -> pd.DataFrame:
    """
    读取 Excel 数据并进行基础清洗。

    清洗步骤：
    1. 时间字段转 datetime，无法解析的置为 NaT（题目要求：不存在则赋空）。
    2. 自动定位并转换骑行距离列为数值，无法解析的置为 NaN。
    3. 从 start_time 衍生出 date、hour、weekday 等常用维度。
    4. 如果原始 weekday 字段缺失，则根据日期自动填充中文星期。

    参数:
        file_path: Excel 文件路径
        sheet_name: 工作表名称
    返回:
        清洗后的 DataFrame
    """
    # 读取 Excel
    df = pd.read_excel(file_path, sheet_name=sheet_name)

    # --- 时间字段清洗 ---
    # errors='coerce' 会把无法解析的值变成 NaT（时间类型的“空值”）
    df['start_time'] = pd.to_datetime(df['start_time'], errors='coerce')
    df['end_time'] = pd.to_datetime(df['end_time'], errors='coerce')

    # --- 骑行距离字段清洗 ---
    distance_col = find_distance_column(df)
    df = df.rename(columns={distance_col: 'distance'})
    df['distance'] = pd.to_numeric(df['distance'], errors='coerce')

    # --- 衍生时间维度 ---
    # 先判断 start_time 是否有效，避免无效日期导致 dt 访问器报错
    if df['start_time'].notna().any():
        df['date'] = df['start_time'].dt.date          # 日期，如 2016-08-01
        df['hour'] = df['start_time'].dt.hour          # 小时，0~23
        df['weekday'] = df['start_time'].dt.dayofweek  # 0=周一, ..., 6=周日
    else:
        # 极端情况：如果 start_time 全部为空，则这些衍生列也置为空
        df['date'] = pd.NaT
        df['hour'] = pd.NA
        df['weekday'] = pd.NA

    # --- 中文星期处理 ---
    # 若原始 start_weekday 列存在且全部缺失，则用上面算出的 weekday 自动填充
    if 'start_weekday' in df.columns and df['start_weekday'].isnull().all():
        df['start_weekday'] = df['weekday'].map(WEEKDAY_MAP)

    return df


def add_distance_bin(df: pd.DataFrame,
                     bins: List[float] = DISTANCE_BINS,
                     labels: List[str] = DISTANCE_LABELS) -> pd.DataFrame:
    """
    为 DataFrame 增加距离分段列，返回新的 DataFrame，不修改原表。

    使用 pd.cut 进行分段：
    - bins: 分段边界
    - labels: 每段标签
    - right=False: 表示左闭右开区间，例如 1 会落在 [1,2) 而不是 [0,1)
    """
    result = df.copy()
    result['distance_bin'] = pd.cut(
        result['distance'],
        bins=bins,
        labels=labels,
        right=False
    )
    return result


# ============================================================
# 第 4 部分：通用工具函数
# ============================================================

def save_csv(df: pd.DataFrame, file_name: str, output_dir: str = OUTPUT_DIR) -> str:
    """
    将 DataFrame 保存为 UTF-8-BOM 编码的 CSV，方便 Excel 直接打开中文不乱码。

    参数:
        df: 要保存的数据
        file_name: CSV 文件名
        output_dir: 输出目录
    返回:
        保存后的完整路径
    """
    path = os.path.join(output_dir, file_name)
    df.to_csv(path, index=False, encoding='utf-8-sig')
    print(f'[保存] {path}')
    return path


def save_figure(fig: plt.Figure, file_name: str, output_dir: str = OUTPUT_DIR, dpi: int = FIG_DPI) -> str:
    """
    保存 matplotlib 图表并关闭，释放内存。
    """
    path = os.path.join(output_dir, file_name)
    fig.savefig(path, dpi=dpi, bbox_inches='tight')
    plt.close(fig)
    print(f'[保存] {path}')
    return path


# ============================================================
# 第 5 部分：4 项分析任务
# ============================================================

def analyze_daily_usage(df: pd.DataFrame) -> pd.DataFrame:
    """
    任务 1：统计全月每日单车使用量。

    返回 DataFrame 包含：
    - date: 日期
    - date_str: 月-日格式字符串，用于图表横轴
    - order_count: 当日订单量
    """
    daily = df.groupby('date').size().reset_index(name='order_count')
    # date 是 date 对象，转字符串后取 "MM-DD" 部分
    daily['date_str'] = daily['date'].astype(str).str[5:]
    return daily[['date', 'date_str', 'order_count']]


def plot_daily_usage(daily: pd.DataFrame,
                     output_dir: str = OUTPUT_DIR,
                     title: str | None = None) -> str:
    """
    绘制每日使用量柱状图。
    """
    # 如果未指定标题，自动从数据推断月份
    if title is None and not daily.empty:
        first_date = pd.to_datetime(daily['date'].iloc[0])
        title = f'{first_date.year}年{first_date.month}月每日单车使用量'
    title = title or '每日单车使用量'

    fig, ax = plt.subplots(figsize=(14, 5))
    ax.bar(daily['date_str'], daily['order_count'], color='steelblue')
    ax.set_title(title)
    ax.set_xlabel('日期')
    ax.set_ylabel('订单量')
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    return save_figure(fig, 'daily_usage.png', output_dir)


def analyze_hourly_weekday(df: pd.DataFrame) -> pd.DataFrame:
    """
    任务 2：周一至周日全天 24 小时用车分布。

    返回“宽表”：行是星期，列是 0~23 小时，值是订单量。
    如果某小时没有订单，则补 0，保证每行都有 24 列。
    """
    # groupby + unstack: 把 hour 从行变列
    pivot = df.groupby(['weekday', 'hour']).size().unstack(fill_value=0)
    # reindex 列，确保 0~23 都存在
    pivot = pivot.reindex(columns=range(24), fill_value=0)
    # 把数字 weekday 映射为中文
    pivot.index = [WEEKDAY_MAP[i] for i in pivot.index]
    return pivot


def plot_hourly_weekday(pivot: pd.DataFrame, output_dir: str = OUTPUT_DIR) -> str:
    """
    绘制周一至周日 24 小时折线图。
    """
    fig, ax = plt.subplots(figsize=DEFAULT_FIGSIZE)
    # 从 tab10 色图中取 7 种颜色
    colors = plt.cm.tab10(np.linspace(0, 1, len(pivot)))
    for idx, (day, row) in enumerate(pivot.iterrows()):
        ax.plot(row.index, row.values, marker='o', label=day, color=colors[idx])

    ax.set_title('周一至周日全天 24 小时用车分布')
    ax.set_xlabel('小时')
    ax.set_ylabel('订单量')
    ax.set_xticks(range(24))
    ax.legend()
    ax.grid(True, linestyle='--', alpha=0.5)
    plt.tight_layout()
    return save_figure(fig, 'hourly_weekday.png', output_dir)


def analyze_hourly_workday_weekend(df: pd.DataFrame) -> pd.DataFrame:
    """
    任务 3：工作日、周末不同时段用车差异。

    返回宽表：行是“工作日/周末”，列是 0~23 小时。
    """
    # 用 .copy() 避免修改传入的 df
    data = df.copy()
    data['day_type'] = data['weekend'].map(DAY_TYPE_MAP)
    pivot = data.groupby(['day_type', 'hour']).size().unstack(fill_value=0)
    pivot = pivot.reindex(columns=range(24), fill_value=0)
    return pivot


def plot_hourly_workday_weekend(pivot: pd.DataFrame, output_dir: str = OUTPUT_DIR) -> str:
    """
    绘制工作日与周末用车差异折线图。
    """
    fig, ax = plt.subplots(figsize=DEFAULT_FIGSIZE)
    for day_type, row in pivot.iterrows():
        ax.plot(row.index, row.values, marker='o', label=day_type, linewidth=2)

    ax.set_title('工作日与周末不同时段用车差异')
    ax.set_xlabel('小时')
    ax.set_ylabel('订单量')
    ax.set_xticks(range(24))
    ax.legend()
    ax.grid(True, linestyle='--', alpha=0.5)
    plt.tight_layout()
    return save_figure(fig, 'hourly_workday_weekend.png', output_dir)


def analyze_distance_distribution(df: pd.DataFrame,
                                  bins: List[float] = DISTANCE_BINS,
                                  labels: List[str] = DISTANCE_LABELS) -> pd.DataFrame:
    """
    任务 4：统计不同骑行距离的订单占比。

    返回 DataFrame 包含：
    - distance_bin: 距离区间
    - order_count: 订单数
    - proportion: 占比（小数）
    - percentage: 占比（%）
    """
    data = add_distance_bin(df, bins=bins, labels=labels)
    dist = data['distance_bin'].value_counts().sort_index().reset_index()
    dist.columns = ['distance_bin', 'order_count']

    total = dist['order_count'].sum()
    dist['proportion'] = dist['order_count'] / total
    dist['percentage'] = (dist['proportion'] * 100).round(2)
    return dist


def plot_distance_distribution(dist: pd.DataFrame, output_dir: str = OUTPUT_DIR) -> str:
    """
    绘制骑行距离订单占比饼图。
    """
    fig, ax = plt.subplots(figsize=(8, 8))
    colors = plt.cm.Set3(np.linspace(0, 1, len(dist)))
    ax.pie(
        dist['order_count'],
        labels=dist['distance_bin'],
        autopct='%1.2f%%',
        startangle=140,
        colors=colors,
        explode=[0.02] * len(dist)
    )
    ax.set_title('不同骑行距离的订单占比')
    plt.tight_layout()
    return save_figure(fig, 'distance_distribution.png', output_dir)


# ============================================================
# 第 6 部分：主程序
# ============================================================

def run_all(file_path: str = DATA_FILE,
            sheet_name: str = SHEET_NAME,
            output_dir: str = OUTPUT_DIR) -> dict[str, pd.DataFrame]:
    """
    执行全部分析任务。

    参数:
        file_path: 输入 Excel 路径
        sheet_name: 工作表名
        output_dir: 输出目录
    返回:
        包含 4 项分析结果 DataFrame 的字典
    """
    # 初始化环境与目录
    set_chinese_font()
    ensure_output_dir(output_dir)

    # 加载并清洗数据
    df = load_data(file_path, sheet_name)
    print(f'数据集共 {len(df)} 条订单记录')
    print(f'时间范围：{df["start_time"].min()} 至 {df["start_time"].max()}')

    # 任务 1：每日使用量
    daily = analyze_daily_usage(df)
    save_csv(daily, 'daily_usage.csv', output_dir)
    plot_daily_usage(daily, output_dir)

    # 任务 2：24 小时 × 星期
    hourly_weekday = analyze_hourly_weekday(df)
    save_csv(hourly_weekday.reset_index(), 'hourly_weekday.csv', output_dir)
    plot_hourly_weekday(hourly_weekday, output_dir)

    # 任务 3：24 小时 × 工作日/周末
    hourly_workday_weekend = analyze_hourly_workday_weekend(df)
    save_csv(hourly_workday_weekend.reset_index(), 'hourly_workday_weekend.csv', output_dir)
    plot_hourly_workday_weekend(hourly_workday_weekend, output_dir)

    # 任务 4：距离分布
    distance_dist = analyze_distance_distribution(df)
    save_csv(distance_dist, 'distance_distribution.csv', output_dir)
    plot_distance_distribution(distance_dist, output_dir)

    print('\n分析完成，结果保存在：', os.path.abspath(output_dir))

    return {
        'daily_usage': daily,
        'hourly_weekday': hourly_weekday,
        'hourly_workday_weekend': hourly_workday_weekend,
        'distance_distribution': distance_dist
    }


def main() -> None:
    """命令行入口。"""
    run_all()


if __name__ == '__main__':
    main()
