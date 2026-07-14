#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国家岩矿化石标本资源共享平台 标本数据爬虫
目标：http://www.nimrf.net.cn/yk/tindex
任务：
1. 在标本查询页抓取平台资源号、资源名、产地等基础信息；
   资源目录实际包含 4 类（矿物/岩石/矿石/化石），每类抓取 2000 条。
2. 对每个标本详情页中的“矿物专属信息”进行解析，保存为标准 JSON。

说明：网站资源目录实际为 4 类（dictValue=2,3,4,5），与页面左侧分类树一致；
      程序按这 4 类分别抓取 2000 条，缺失字段统一置为空字符串。
"""

# 导入 json 模块，用于解析 API 返回的 JSON 数据以及写入 JSON 文件
import json
# 导入 os 模块，用于处理文件路径、创建目录等操作系统相关操作
import os
# 导入 time 模块，用于在请求之间添加延时，避免请求过快
import time
# 导入 traceback 模块，用于打印详细的异常堆栈信息
import traceback
# 导入 argparse 模块，用于解析命令行参数，如 --per-category、--categories
import argparse
# 从 concurrent.futures 导入 ThreadPoolExecutor 和 as_completed
# ThreadPoolExecutor 用于创建线程池并发抓取详情页
# as_completed 用于在任务完成时按完成顺序获取结果
from concurrent.futures import ThreadPoolExecutor, as_completed
# 从 datetime 导入 datetime，用于记录抓取时间
from datetime import datetime
# 从 urllib.parse 导入 urlencode，用于将字典参数编码为 URL 查询字符串
from urllib.parse import urlencode

# 导入 requests 库，用于发送 HTTP 请求
import requests
# 从 requests.adapters 导入 HTTPAdapter，用于配置连接池和重试策略
from requests.adapters import HTTPAdapter
# 从 urllib3.util.retry 导入 Retry，用于定义重试规则
from urllib3.util.retry import Retry


# 定义 API 基础地址，所有数据接口都在此前缀下
BASE_URL = "http://www.nimrf.net.cn/prod-api"
# 定义标本查询页地址，作为 Referer 使用，模拟正常浏览器访问
INDEX_URL = "http://www.nimrf.net.cn/yk/tindex"
# 定义浏览器 User-Agent，模拟 Chrome 浏览器，降低被反爬拦截的概率
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 定义输出目录：脚本所在目录下的 data 文件夹
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
# 定义每类默认抓取数量：2000 条
DEFAULT_PER_CATEGORY = 2000
# 定义列表页每页大小：经测试 200 条可用，10 页即可抓完 2000 条
PAGE_SIZE = 200
# 定义详情页并发线程数：5 个线程同时抓取详情
DETAIL_WORKERS = 5
# 定义请求失败时总重试次数
RETRY_TOTAL = 5
# 定义重试间隔退避因子，用于计算每次重试前的等待时间
RETRY_BACKOFF = 1.0

# 定义矿物专属信息字段映射：将详情 API 中的拼音字段名映射为示例 JSON 中的英文字段名
MINERAL_DETAIL_FIELD_MAP = {
    "ddgzwz": "geotectonicPosition",       # 大地构造位置
    "dzt": "geologicalBody",               # 地质体
    "dzcz": "geologicalOccurrence",        # 地质产状
    "xcsd": "formationAge",                # 形成时代
    "cy": "genesis",                       # 成因
    "jthxs": "crystalChemicalFormula",     # 晶体化学式
    "jx": "crystalSystem",                 # 晶系
    "xt": "morphology",                    # 形态
    "ys": "color",                         # 颜色
    "th": "streak",                        # 条痕
    "tmd": "transparency",                 # 透明度
    "gz": "luster",                        # 光泽
    "yg": "fluorescence",                  # 荧光
    "lg": "phosphorescence",               # 磷光
    "khyd": "scratchHardness",             # 刻划硬度
    "xdmd": "relativeDensity",             # 相对密度
    "jl": "cleavage",                      # 解理
    "ll": "cleavage_2",                    # 裂理
    "dk": "rupture",                       # 断口
    "qtwlxz": "otherPhysicalProperties",   # 其他物理性质
    "xwjgxxz": "microscopicOpticalProperties",  # 显微镜下光学性质
    "cczl": "sizeAndMass",                 # 尺寸和质量
    "yszl": "originalData",                # 原始资料
    "wxzl": "literature",                  # 文献资料
    "cjsj": "collectionTime",              # 采集时间
}


def create_session():
    """创建带重试机制的 requests Session。"""
    # 创建一个 requests Session 对象，Session 会在多次请求间复用 TCP 连接，提高效率
    session = requests.Session()
    # 更新 Session 的请求头，模拟真实浏览器请求
    session.headers.update({
        # 设置 User-Agent，让服务器认为是浏览器访问
        "User-Agent": USER_AGENT,
        # 设置 Accept，表示希望接收 JSON 或纯文本响应
        "Accept": "application/json, text/plain, */*",
        # 设置 Accept-Language，表示接受中文和英文
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        # 设置 Referer，表示请求来自标本查询页，进一步模拟正常访问
        "Referer": INDEX_URL,
    })
    # 创建重试策略对象
    retry_strategy = Retry(
        # 总重试次数为 5 次
        total=RETRY_TOTAL,
        # 退避因子，重试间隔为 backoff_factor * (2 ** (retry - 1)) 秒
        backoff_factor=RETRY_BACKOFF,
        # 针对以下 HTTP 状态码进行重试：429（请求过多）、500、502、503、504（服务端错误）
        status_forcelist=[429, 500, 502, 503, 504],
        # 只允许对 GET 请求进行重试
        allowed_methods=["GET"],
    )
    # 创建 HTTP 适配器，传入重试策略、连接池初始连接数和最大连接数
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=20)
    # 将适配器挂载到 http:// 前缀的所有请求上
    session.mount("http://", adapter)
    # 将适配器挂载到 https:// 前缀的所有请求上（虽然当前未使用，但保留兼容性）
    session.mount("https://", adapter)
    # 返回配置好的 Session 对象
    return session


def safe_value(value):
    """将 None 转换为空字符串，其他值转为字符串。"""
    # 如果值为 None，按题目要求返回空字符串作为缺失值
    if value is None:
        return ""
    # 否则将值转换为字符串，并去除首尾空白字符
    return str(value).strip()


def fetch_categories(session):
    """获取资源分类字典。"""
    # 构造获取分类字典的 URL，yk_category 对应页面左侧分类树
    url = f"{BASE_URL}/ykhs/web/dict/data/type/yk_category"
    # 使用 Session 发送 GET 请求，超时时间为 20 秒
    resp = session.get(url, timeout=20)
    # 如果响应状态码不是 2xx，抛出 HTTPError 异常
    resp.raise_for_status()
    # 将响应体解析为 Python 字典
    data = resp.json()
    # 检查业务状态码是否为 200，若不是则说明请求失败
    if data.get("code") != 200:
        # 抛出运行时错误，附带返回数据以便排查
        raise RuntimeError(f"获取分类失败: {data}")
    # 初始化空列表，用于存放整理后的分类信息
    categories = []
    # 遍历返回数据中的分类项
    for item in data.get("data", []):
        # 将每个分类整理为字典，包含分类值、分类名称和 source（后续推断）
        categories.append({
            # dictValue 为分类编号：2=矿物、3=岩石、4=矿石、5=化石
            "value": item["dictValue"],
            # dictLabel 为分类中文名称
            "label": item["dictLabel"],
            # source 初始为 None，后续从列表接口返回的数据中推断
            "source": None,
        })
    # 返回分类列表
    return categories


def fetch_list_page(session, category_value, page_num, page_size=PAGE_SIZE):
    """抓取列表页。"""
    # 构造查询参数字典
    params = {
        # pageNum 表示当前页码
        "pageNum": page_num,
        # pageSize 表示每页条数
        "pageSize": page_size,
        # delFlag=0 表示未删除的数据
        "delFlag": 0,
        # category 表示分类编号
        "category": category_value,
    }
    # 使用 urlencode 将参数编码为查询字符串，拼接成完整 URL
    url = f"{BASE_URL}/ykhs/web/mtYkDataAll/list?{urlencode(params)}"
    # 发送 GET 请求，超时 30 秒
    resp = session.get(url, timeout=30)
    # 检查响应状态码
    resp.raise_for_status()
    # 解析 JSON 响应
    data = resp.json()
    # 检查业务状态码
    if data.get("code") != 200:
        raise RuntimeError(f"列表页请求失败: {data}")
    # 返回当前页数据 rows 和总条数 total
    return data.get("rows", []), data.get("total", 0)


def fetch_detail(session, source, ptzyh):
    """抓取标本详情（矿物专属信息）。"""
    # 构造详情接口 URL，source 为 mineral/rock/ore/fossil，ptzyh 为平台资源号
    url = f"{BASE_URL}/ykhs/web/mtYkDataAll/detail/{source}/{ptzyh}"
    # 发送 GET 请求，超时 30 秒
    resp = session.get(url, timeout=30)
    # 检查响应状态码
    resp.raise_for_status()
    # 解析 JSON 响应
    data = resp.json()
    # 检查业务状态码
    if data.get("code") != 200:
        raise RuntimeError(f"详情页请求失败: {data}")
    # 返回 data 字段内容；若 data 为 None 则返回空字典，避免后续报错
    return data.get("data", {}) or {}


def build_specimen(list_row, detail_data):
    """将列表记录与详情记录组装为示例 JSON 格式。"""
    # 从列表记录中获取资源管理部门/分类对象，若不存在则使用空字典
    zyglbm = list_row.get("zyglbm") or {}
    # 分类编码优先取 name（如“单质”“片岩”），若没有 name 则取 code，否则为空
    classification_code = zyglbm.get("name") or zyglbm.get("code") or ""

    # 初始化矿物专属信息字典
    detailed_info = {}
    # 遍历字段映射表，将详情 API 字段转换为示例 JSON 字段
    for src_key, dst_key in MINERAL_DETAIL_FIELD_MAP.items():
        # 从详情数据中取值
        value = detail_data.get(src_key)
        # 如果值为 None 且当前字段是采集时间 cjsj，则回退到列表数据中的 cjsj
        if value is None and src_key == "cjsj":
            value = list_row.get("cjsj")
        # 使用 safe_value 处理缺失值后存入 detailed_info
        detailed_info[dst_key] = safe_value(value)

    # 构造最终的标本对象，结构与题目示例完全一致
    specimen = {
        "specimen": {
            # platformResourceNumber：平台资源号
            "platformResourceNumber": safe_value(list_row.get("ptzyh")),
            # resourceName：资源名称
            "resourceName": safe_value(list_row.get("zym")),
            # foreignName：资源外文名称
            "foreignName": safe_value(list_row.get("zywwm")),
            # origin：产地
            "origin": safe_value(list_row.get("cd")),
            # classificationCode：资源归类编码
            "classificationCode": safe_value(classification_code),
            # storageLocation：库存位置号
            "storageLocation": safe_value(list_row.get("ktybh")),
            # detailedInfo：矿物专属信息
            "detailedInfo": detailed_info,
        }
    }
    # 返回组装好的标本字典
    return specimen


def scrape_category(session, category_value, target_count=DEFAULT_PER_CATEGORY):
    """抓取单个分类的标本列表并获取详情。"""
    # 打印开始信息，flush=True 确保立即输出到日志
    print(f"\n[开始] 分类 category={category_value}，目标 {target_count} 条", flush=True)

    # 1. 抓取列表：循环翻页直到达到目标数量或没有更多数据
    all_rows = []  # 用于存放所有抓取到的列表记录
    page_num = 1   # 从第 1 页开始
    while len(all_rows) < target_count:
        # 调用 fetch_list_page 抓取当前页
        rows, total = fetch_list_page(session, category_value, page_num, PAGE_SIZE)
        # 如果当前页没有数据，说明已到达末尾
        if not rows:
            print(f"  分类 {category_value} 在第 {page_num} 页无数据，总数 {total}", flush=True)
            break
        # 将当前页记录追加到总列表中
        all_rows.extend(rows)
        print(f"  列表页 {page_num}: 获取 {len(rows)} 条，累计 {len(all_rows)}/{target_count}", flush=True)
        # 如果当前页返回条数不足 page_size，说明是最后一页
        if len(rows) < PAGE_SIZE:
            break
        # 页码加 1，准备抓取下一页
        page_num += 1
        # 列表页请求间隔 0.3 秒，避免请求过快对服务端造成压力
        time.sleep(0.3)

    # 截取前 target_count 条，避免超过目标数量
    all_rows = all_rows[:target_count]
    # 如果没有任何数据，打印警告并返回空列表
    if not all_rows:
        print(f"[警告] 分类 {category_value} 未获取到任何数据", flush=True)
        return []

    # 从第一条记录中推断 source 字段（mineral/rock/ore/fossil），详情接口需要用到
    source = all_rows[0].get("source")
    # 如果 source 为空，详情接口 URL 将无法正确构造，提前退出
    if not source:
        print(f"[错误] 分类 {category_value} 无法获取 source 字段，跳过详情抓取", flush=True)
        # 不抓详情，直接用空详情组装基础信息
        return [build_specimen(row, {}) for row in all_rows]
    print(f"  分类 source={source}，共 {len(all_rows)} 条待获取详情", flush=True)

    # 2. 并发获取详情
    specimens = []  # 存放带有原始索引的标本结果
    errors = []     # 存放抓取失败的记录

    # 定义单个抓取任务函数，接收 (索引, 记录) 元组
    def fetch_one(idx_row):
        idx, row = idx_row
        # 获取当前记录的平台资源号
        ptzyh = row.get("ptzyh")
        try:
            # 请求前加延时，避免 5 线程并发打满服务器导致限流
            time.sleep(0.1)
            # 抓取详情数据
            detail = fetch_detail(session, source, ptzyh)
            # 组装成标准 JSON 格式
            specimen = build_specimen(row, detail)
            # 返回索引、标本对象、无错误
            return idx, specimen, None
        except Exception as exc:
            # 如果发生异常，返回索引、None、错误信息（包含 ptzyh 和异常描述）
            return idx, None, (ptzyh, str(exc))

    # 创建线程池，最大并发数为 DETAIL_WORKERS
    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as executor:
        # 提交所有详情抓取任务，返回 future 到索引的映射
        futures = {executor.submit(fetch_one, (i, row)): i for i, row in enumerate(all_rows)}
        # 按任务完成顺序遍历结果
        for future in as_completed(futures):
            # 获取任务返回值
            idx, specimen, err = future.result()
            # 如果存在错误
            if err:
                # 将错误信息加入错误列表
                errors.append(err)
                # 失败时仍然保留基础信息，详情字段置空（传入空字典）
                specimen = build_specimen(all_rows[idx], {})
            # 将结果与原始索引一起保存，便于后续排序
            specimens.append((idx, specimen))
            # 每完成 100 条打印一次进度
            if (len(specimens) % 100) == 0:
                print(f"  详情进度: {len(specimens)}/{len(all_rows)}", flush=True)

    # 按原始索引排序，保证输出顺序与列表顺序一致
    specimens.sort(key=lambda x: x[0])
    # 提取排序后的标本对象
    result = [s for _, s in specimens]

    # 打印完成信息，包含成功条数和失败条数
    print(f"[完成] 分类 {category_value}({source})：成功 {len(result)} 条，详情失败 {len(errors)} 条", flush=True)
    # 如果有失败记录，打印前 5 条作为示例
    if errors:
        print(f"  失败示例: {errors[:5]}", flush=True)
    # 返回该分类的所有标本对象
    return result


def save_json(data, filepath):
    """保存 JSON 文件，确保中文可读。"""
    # 如果文件所在目录不存在，则递归创建
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    # 以 UTF-8 编码打开文件写入模式
    with open(filepath, "w", encoding="utf-8") as f:
        # 将数据写入文件，ensure_ascii=False 保证中文正常显示，indent=2 表示 2 空格缩进
        json.dump(data, f, ensure_ascii=False, indent=2)
    # 打印保存信息
    print(f"[保存] {filepath}，共 {len(data)} 条", flush=True)


def save_summary(summary, filepath):
    """保存抓取摘要。"""
    # 如果文件所在目录不存在，则递归创建
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    # 以 UTF-8 编码打开文件写入模式
    with open(filepath, "w", encoding="utf-8") as f:
        # 写入摘要 JSON
        json.dump(summary, f, ensure_ascii=False, indent=2)
    # 打印保存信息
    print(f"[保存] {filepath}", flush=True)


def diagnose(session):
    """诊断模式：打印 API 返回的原始数据，对比实际输出。"""
    print("=" * 60)
    print("[诊断] 开始 API 数据诊断")
    print("=" * 60)

    # 1. 检查分类接口
    print("\n--- 1. 分类接口 ---")
    url = f"{BASE_URL}/ykhs/web/dict/data/type/yk_category"
    resp = session.get(url, timeout=20)
    cat_data = resp.json()
    print(f"状态码: {cat_data.get('code')}")
    cats = cat_data.get("data", [])
    print(f"分类数量: {len(cats)}")
    for c in cats:
        print(f"  value={c.get('dictValue')!r} ({type(c.get('dictValue')).__name__}), "
              f"label={c.get('dictLabel')!r}")
    if not cats:
        print("[!!!] 分类为空，数据一定不对！")
        return

    # 2. 检查列表接口（每类抓 1 页）
    print("\n--- 2. 列表接口（每类第 1 页） ---")
    for c in cats:
        val = c["dictValue"]
        label = c["dictLabel"]
        params = {"pageNum": 1, "pageSize": 5, "delFlag": 0, "category": val}
        url = f"{BASE_URL}/ykhs/web/mtYkDataAll/list?{urlencode(params)}"
        resp = session.get(url, timeout=30)
        list_data = resp.json()
        rows = list_data.get("rows", [])
        total = list_data.get("total", 0)
        print(f"  [{label}] total={total}, 本页={len(rows)}条")
        if rows:
            # 打印第一条的所有字段名和值
            row = rows[0]
            print(f"    第一条字段:")
            for k, v in row.items():
                print(f"      {k} = {v!r}  ({type(v).__name__})")
            # 检查关键的 source 字段
            source = row.get("source")
            print(f"    → source = {source!r}")
            # 检查关键的 zyglbm 字段
            zyglbm = row.get("zyglbm") or {}
            print(f"    → zyglbm = {zyglbm!r}")
        else:
            print(f"    [!!!] {label} 列表为空，可能是 category 参数值不对！")

    # 3. 检查详情接口
    print("\n--- 3. 详情接口（取第一个分类第一条） ---")
    for c in cats:
        val = c["dictValue"]
        params = {"pageNum": 1, "pageSize": 1, "delFlag": 0, "category": val}
        url = f"{BASE_URL}/ykhs/web/mtYkDataAll/list?{urlencode(params)}"
        resp = session.get(url, timeout=30)
        rows = resp.json().get("rows", [])
        if not rows:
            continue
        row = rows[0]
        source = row.get("source")
        ptzyh = row.get("ptzyh")
        if source and ptzyh:
            detail_url = f"{BASE_URL}/ykhs/web/mtYkDataAll/detail/{source}/{ptzyh}"
            detail_resp = session.get(detail_url, timeout=30)
            detail_data = detail_resp.json()
            print(f"  source={source}, ptzyh={ptzyh}")
            print(f"  详情状态码: {detail_data.get('code')}")
            dd = detail_data.get("data", {}) or {}
            print(f"  详情字段数: {len(dd)}")
            for k, v in list(dd.items())[:5]:
                print(f"    {k} = {str(v)[:60]!r}")
            if not dd:
                print(f"  [!!!] 详情数据为空！")
            # 检查字段映射是否命中
            mapped_keys = set(MINERAL_DETAIL_FIELD_MAP.keys())
            actual_keys = set(dd.keys())
            hit = mapped_keys & actual_keys
            miss = mapped_keys - actual_keys
            print(f"  字段映射命中: {len(hit)}/{(len(mapped_keys))}")
            if miss:
                print(f"  未命中的映射字段: {sorted(miss)[:10]}")
        break  # 只测一个分类

    print("\n" + "=" * 60)
    print("[诊断] 完成，请把以上输出发给开发者分析")
    print("=" * 60)


def main():
    # 创建命令行参数解析器
    parser = argparse.ArgumentParser(description="国家岩矿化石标本资源共享平台数据爬虫")
    # 添加 --per-category 参数，用于指定每类抓取数量
    parser.add_argument(
        "--per-category",
        type=int,
        default=DEFAULT_PER_CATEGORY,
        help=f"每类抓取数量（默认 {DEFAULT_PER_CATEGORY}）",
    )
    # 添加 --categories 参数，用于指定只抓取哪些分类
    parser.add_argument(
        "--categories",
        type=str,
        default="",
        help="指定分类值，逗号分隔，例如 2,3,4,5；默认抓取全部分类",
    )
    # 添加 --diagnose 参数，用于诊断 API 数据
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="诊断模式：打印 API 原始数据，排查数据问题",
    )
    # 解析命令行参数
    args = parser.parse_args()

    # 创建输出目录（如果不存在）
    os.makedirs(DATA_DIR, exist_ok=True)
    # 创建带重试机制的 HTTP Session
    session = create_session()

    # 如果启用了诊断模式，跑完诊断就退出
    if args.diagnose:
        diagnose(session)
        session.close()
        return

    # 提前初始化 summary，确保异常处理时变量一定存在
    summary = {"categories": []}

    try:
        # 获取网站分类字典
        categories = fetch_categories(session)
        # 打印分隔线和分类信息
        print("=" * 60, flush=True)
        print("获取到网站分类：", flush=True)
        for cat in categories:
            print(f"  {cat['value']}: {cat['label']}", flush=True)
        print("=" * 60, flush=True)

        # 如果用户通过 --categories 指定了分类，则过滤分类列表
        if args.categories:
            # 将逗号分隔的字符串转换为集合
            selected_values = set(args.categories.split(","))
            # 只保留用户指定的分类
            categories = [c for c in categories if c["value"] in selected_values]

        # 初始化摘要字典
        summary = {
            "source_url": INDEX_URL,          # 来源页面地址
            "api_base": BASE_URL,             # API 基础地址
            "crawl_time": datetime.now().isoformat(),  # 抓取时间（ISO 格式）
            "per_category": args.per_category, # 每类抓取数量
            "categories": [],                  # 分类统计列表
        }

        # 遍历每个分类进行抓取
        for cat in categories:
            # 获取分类编号
            cat_value = cat["value"]
            # 抓取该分类的数据
            specimens = scrape_category(session, cat_value, args.per_category)

            # 保存该分类 JSON 文件
            # 将分类名称中的非字母数字字符去除，用于生成安全文件名
            safe_label = "".join(c for c in cat["label"] if c.isalnum()) or cat_value
            # 进一步限制文件名长度，防止过长
            safe_label = safe_label[:50]
            # 构造文件名：specimens_分类名_分类值.json
            filename = f"specimens_{safe_label}_{cat_value}.json"
            # 使用 os.path.basename 防止路径遍历，确保只使用文件名部分
            filename = os.path.basename(filename)
            # 构造完整文件路径
            filepath = os.path.join(DATA_DIR, filename)
            # 保存 JSON
            save_json(specimens, filepath)

            # 将该分类统计信息加入摘要
            summary["categories"].append({
                "value": cat_value,
                "label": cat["label"],
                "count": len(specimens),
                "filename": filename,
            })

        # 计算总条数并保存摘要
        summary["total"] = sum(c["count"] for c in summary["categories"])
        summary_path = os.path.join(DATA_DIR, "summary.json")
        save_summary(summary, summary_path)

        # 打印全部完成信息
        print("\n" + "=" * 60, flush=True)
        print(f"全部完成，总计 {summary['total']} 条，数据保存在 {DATA_DIR}", flush=True)
        print("=" * 60, flush=True)

    except KeyboardInterrupt:
        # 用户按 Ctrl+C 中断时，保存已完成的分类数据和摘要
        print("\n\n[中断] 用户手动停止，正在保存已抓取的数据...", flush=True)
        if summary.get("categories"):
            summary["total"] = sum(c["count"] for c in summary["categories"])
            summary["interrupted"] = True
            summary_path = os.path.join(DATA_DIR, "summary.json")
            save_summary(summary, summary_path)
            print(f"[已保存] 数据保存在 {DATA_DIR}，已抓取 {summary['total']} 条", flush=True)

    except Exception as exc:
        # 其他异常：保存已有数据后重新抛出
        print(f"\n[异常] {exc}", flush=True)
        traceback.print_exc()
        if summary.get("categories"):
            summary["total"] = sum(c["count"] for c in summary["categories"])
            summary["error"] = str(exc)
            summary_path = os.path.join(DATA_DIR, "summary.json")
            save_summary(summary, summary_path)
            print(f"[已保存] 数据保存在 {DATA_DIR}，已抓取 {summary['total']} 条", flush=True)

    finally:
        # 无论成功、中断还是异常，确保关闭 Session，释放连接资源
        session.close()


# 当脚本被直接运行时执行 main() 函数
if __name__ == "__main__":
    main()
