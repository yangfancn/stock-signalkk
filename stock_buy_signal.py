# -*- coding: utf-8 -*-
"""
沪深300买入信号自动推送脚本
==========================
功能：扫描沪深300，筛选买入信号股票，通过Server酱推送到微信。
运行环境：GitHub Actions（云端定时运行，不需要开电脑）
买入信号：5日金叉10日 + 股价上穿20日 + 多头排列 + 成交量放大
"""

import os
import json
import time
import datetime
import warnings
import traceback

import pandas as pd

warnings.filterwarnings("ignore")

# ============================================================
#   参数配置
# ============================================================

MA_V1 = 5
MA_V2 = 10
MA_V3 = 20
MA_V4 = 60
VOLUME_SURGE_RATIO = 1.5
MA_TREND_DAYS = 5
SLEEP_BETWEEN = 0.3

# Server酱密钥（从环境变量读取，GitHub Actions中通过Secrets配置）
SERVERCHAN_KEY = os.environ.get("SERVERCHAN_KEY", "")


# ============================================================
#   工具函数
# ============================================================

def code_to_sina(code):
    code = str(code).zfill(6)
    return ("sh" if code.startswith("6") else "sz") + code


# ============================================================
#   股票数据获取（新浪财经 + 腾讯财经）
# ============================================================

def get_history_sina(code, days=300):
    import requests
    sina_code = code_to_sina(code)
    url = (f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var=/"
           f"CN_MarketDataService.getKLineData?symbol={sina_code}"
           f"&scale=240&ma=no&datalen={days}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://finance.sina.com.cn/"
    }
    r = requests.get(url, headers=headers, timeout=15)
    text = r.text
    start, end = text.find("("), text.rfind(")")
    if start == -1 or end == -1:
        return None
    data = json.loads(text[start + 1:end])
    if not data:
        return None
    df = pd.DataFrame(data)
    df = df.rename(columns={"day": "date", "open": "open", "close": "close",
                            "high": "high", "low": "low", "volume": "volume"})
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "close", "high", "low", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


def get_history_tencent(code, days=300):
    import requests
    tx_code = ("sh" if code.startswith("6") else "sz") + code
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
           f"param={tx_code},day,,,{days},qfq")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    r = requests.get(url, headers=headers, timeout=15)
    data = r.json()
    stock_data = data.get("data", {}).get(tx_code, {})
    klines = stock_data.get("qfqday") or stock_data.get("day") or []
    if not klines:
        return None
    df = pd.DataFrame(klines)
    df.columns = ["date", "open", "close", "high", "low", "volume"] + list(df.columns[6:])
    df = df[["date", "open", "close", "high", "low", "volume"]]
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "close", "high", "low", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


def get_stock_history(code):
    try:
        df = get_history_sina(code)
        if df is not None and len(df) >= 100:
            return df
    except Exception:
        pass
    try:
        df = get_history_tencent(code)
        if df is not None and len(df) >= 100:
            return df
    except Exception:
        pass
    return None


def get_stock_list():
    """获取沪深300股票列表，优先接口，失败用内置列表"""
    try:
        import akshare as ak
        df = ak.index_stock_cons_csindex(symbol="000300")
        if df is not None and len(df) > 0:
            code_col = name_col = None
            for c in df.columns:
                if "成分券代码" in str(c):
                    code_col = c
                if "成分券名称" in str(c):
                    name_col = c
            if code_col is None:
                for c in df.columns:
                    if "代码" in str(c) and "指数" not in str(c):
                        code_col = c
                        break
            if name_col is None:
                for c in df.columns:
                    if "名称" in str(c) and "指数" not in str(c):
                        name_col = c
                        break
            if code_col and name_col:
                result = pd.DataFrame({
                    "代码": df[code_col].astype(str).str.zfill(6),
                    "名称": df[name_col].astype(str)
                })
                result = result[result["代码"] != "000300"]
                result = result[~result["名称"].str.contains("沪深300|指数", na=False)]
                result = result.drop_duplicates(subset=["代码"]).reset_index(drop=True)
                if len(result) >= 200:
                    print(f"获取到沪深300成分股 {len(result)} 只（接口）")
                    return result
    except Exception as e:
        print(f"接口获取失败: {e}，使用内置列表")

    return get_fallback_list()


def get_fallback_list():
    """内置沪深300常见股票列表"""
    stocks = [
        ("600519", "贵州茅台"), ("000858", "五粮液"), ("601318", "中国平安"),
        ("600036", "招商银行"), ("000333", "美的集团"), ("601166", "兴业银行"),
        ("600276", "恒瑞医药"), ("000651", "格力电器"), ("601398", "工商银行"),
        ("600000", "浦发银行"), ("000001", "平安银行"), ("601888", "中国中免"),
        ("600887", "伊利股份"), ("002714", "牧原股份"), ("601012", "隆基绿能"),
        ("300750", "宁德时代"), ("002594", "比亚迪"), ("600900", "长江电力"),
        ("601899", "紫金矿业"), ("600030", "中信证券"), ("000725", "京东方A"),
        ("601668", "中国建筑"), ("600309", "万华化学"), ("002475", "立讯精密"),
        ("601601", "中国太保"), ("600585", "海螺水泥"), ("000568", "泸州老窖"),
        ("000596", "古井贡酒"), ("600809", "山西汾酒"), ("603259", "药明康德"),
        ("300059", "东方财富"), ("002415", "海康威视"), ("000002", "万科A"),
        ("601628", "中国人寿"), ("600048", "保利发展"), ("601390", "中国中铁"),
        ("601186", "中国铁建"), ("600028", "中国石化"), ("601857", "中国石油"),
        ("600050", "中国联通"), ("600941", "中国移动"), ("601728", "中国电信"),
        ("600104", "上汽集团"), ("601238", "广汽集团"), ("000625", "长安汽车"),
        ("600196", "复星医药"), ("002007", "华兰生物"), ("300015", "爱尔眼科"),
        ("300760", "迈瑞医疗"), ("002241", "歌尔股份"), ("002352", "顺丰控股"),
        ("601816", "京沪高铁"), ("600690", "海尔智家"), ("000100", "TCL科技"),
        ("002304", "洋河股份"), ("603288", "海天味业"), ("600438", "通威股份"),
        ("601088", "中国神华"), ("601225", "陕西煤业"), ("002460", "赣锋锂业"),
        ("002466", "天齐锂业"), ("300274", "阳光电源"), ("600436", "片仔癀"),
        ("600085", "同仁堂"), ("000538", "云南白药"), ("601919", "中远海控"),
        ("600026", "中远海能"), ("601872", "招商轮船"), ("600018", "上港集团"),
        ("000063", "中兴通讯"), ("002049", "紫光国微"), ("603501", "韦尔股份"),
        ("603986", "兆易创新"), ("300782", "卓胜微"), ("002371", "北方华创"),
        ("600703", "三安光电"), ("002916", "深南电路"), ("300408", "三环集团"),
        ("002230", "科大讯飞"), ("300033", "同花顺"), ("601519", "大智慧"),
        ("600570", "恒生电子"), ("601336", "新华保险"), ("601688", "华泰证券"),
        ("600837", "海通证券"), ("601211", "国泰君安"), ("000776", "广发证券"),
        ("600999", "招商证券"), ("601995", "中金公司"), ("001979", "招商蛇口"),
        ("601155", "新城控股"), ("600606", "绿地控股"), ("601669", "中国电建"),
        ("601800", "中国交建"), ("601618", "中国中冶"), ("601117", "中国化学"),
        ("000401", "冀东水泥"), ("000877", "天山股份"), ("600801", "华新水泥"),
        ("601992", "金隅集团"), ("000786", "北新建材"), ("600566", "济川药业"),
        ("000423", "东阿阿胶"), ("603899", "晨光股份"), ("601877", "正泰电器"),
        ("600406", "国电南瑞"), ("600089", "特变电工"), ("002129", "TCL中环"),
        ("600031", "三一重工"), ("000157", "中联重科"), ("601766", "中国中车"),
        ("600150", "中国船舶"), ("600038", "中直股份"), ("000768", "中航西飞"),
        ("600893", "航发动力"), ("002025", "航天电器"), ("600760", "中航沈飞"),
        ("000733", "振华科技"), ("600118", "中国卫星"), ("603369", "今世缘"),
        ("600600", "青岛啤酒"), ("600132", "重庆啤酒"), ("000729", "燕京啤酒"),
        ("002508", "老板电器"), ("002032", "苏泊尔"), ("000661", "长春高新"),
        ("300347", "泰格医药"), ("300142", "沃森生物"), ("300122", "智飞生物"),
        ("601607", "上海医药"), ("600867", "通化东宝"), ("000963", "华东医药"),
        ("002001", "新和成"), ("002493", "荣盛石化"), ("600346", "恒力石化"),
        ("000703", "恒逸石化"), ("601233", "桐昆股份"), ("002074", "国轩高科"),
        ("300014", "亿纬锂能"), ("002812", "恩捷股份"), ("300037", "新宙邦"),
        ("002709", "天赐材料"), ("603799", "华友钴业"), ("603993", "洛阳钼业"),
        ("601600", "中国铝业"), ("000807", "云铝股份"), ("600547", "山东黄金"),
        ("600489", "中金黄金"), ("600188", "兖矿能源"), ("600989", "宝丰能源"),
        ("601808", "中海油服"), ("600938", "中国海油"), ("601288", "农业银行"),
        ("601988", "中国银行"), ("601939", "建设银行"), ("601328", "交通银行"),
        ("600015", "华夏银行"), ("601169", "北京银行"), ("600919", "江苏银行"),
        ("601229", "上海银行"), ("002142", "宁波银行"), ("600926", "杭州银行"),
        ("601319", "中国人保"), ("601066", "中信建投"), ("600109", "国金证券"),
        ("000783", "长江证券"), ("600369", "西南证券"), ("601377", "兴业证券"),
        ("600958", "东方证券"), ("601878", "浙商证券"), ("601006", "大秦铁路"),
        ("600377", "宁沪高速"), ("000089", "深圳机场"), ("600009", "上海机场"),
        ("600115", "中国东航"), ("601111", "中国国航"), ("600029", "南方航空"),
        ("601021", "春秋航空"), ("002928", "华夏航空"), ("600660", "福耀玻璃"),
        ("000581", "威孚高科"), ("600741", "华域汽车"), ("002938", "鹏鼎控股"),
        ("002463", "沪电股份"), ("000050", "深天马A"), ("603160", "汇顶科技"),
        ("300661", "圣邦股份"),
    ]
    seen = set()
    unique = []
    for code, name in stocks:
        if code not in seen:
            seen.add(code)
            unique.append((code, name))
    print(f"使用内置沪深300列表，共 {len(unique)} 只")
    return pd.DataFrame(unique, columns=["代码", "名称"])


# ============================================================
#   指标计算与买入信号检测
# ============================================================

def calc_indicators(df):
    if df is None or len(df) < MA_V4 + MA_TREND_DAYS + 5:
        return None
    df = df.copy()
    df["ma5"] = df["close"].rolling(MA_V1).mean()
    df["ma10"] = df["close"].rolling(MA_V2).mean()
    df["ma20"] = df["close"].rolling(MA_V3).mean()
    df["ma60"] = df["close"].rolling(MA_V4).mean()
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    for ma in ["ma5", "ma10", "ma20", "ma60"]:
        df[f"{ma}_slope"] = (df[ma] - df[ma].shift(MA_TREND_DAYS)) / df[ma].shift(MA_TREND_DAYS) * 100
    return df


def detect_buy_signal(df):
    """
    检测买入信号，返回 (是否买入, 信号详情字典)
    买入标准：
      - 5日金叉10日
      - 股价上穿20日均线
      - 均线多头排列（5>10>20>60）
      - 成交量放大
      - 均线向上
    综合评分 >= 5 视为买入信号
    """
    if df is None or len(df) < MA_V4 + 10:
        return False, None

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    for col in ["ma5", "ma10", "ma20", "ma60", "vol_ma5"]:
        if pd.isna(latest[col]):
            return False, None

    price = latest["close"]
    ma5, ma10, ma20, ma60 = latest["ma5"], latest["ma10"], latest["ma20"], latest["ma60"]
    volume = latest["volume"]
    vol_ma5 = latest["vol_ma5"]

    # 各买入信号
    golden_cross_5_10 = (latest["ma5"] > latest["ma10"]) and (prev["ma5"] <= prev["ma10"])
    golden_cross_10_20 = (latest["ma10"] > latest["ma20"]) and (prev["ma10"] <= prev["ma20"])
    price_cross_above_20 = (latest["close"] > latest["ma20"]) and (prev["close"] <= prev["ma20"])
    bullish_alignment = (ma5 > ma10) and (ma10 > ma20) and (ma20 > ma60)
    volume_surge = (not pd.isna(vol_ma5)) and (volume > vol_ma5 * VOLUME_SURGE_RATIO)
    ma5_up = latest["ma5_slope"] > 0 if not pd.isna(latest["ma5_slope"]) else False
    ma10_up = latest["ma10_slope"] > 0 if not pd.isna(latest["ma10_slope"]) else False
    ma20_up = latest["ma20_slope"] > 0 if not pd.isna(latest["ma20_slope"]) else False

    # 综合评分
    score = 0
    if golden_cross_5_10: score += 3
    if golden_cross_10_20: score += 2
    if price_cross_above_20: score += 3
    if bullish_alignment: score += 2
    if volume_surge and latest["close"] > prev["close"]: score += 2
    if ma5_up and ma10_up and ma20_up: score += 2
    if price > ma20: score += 1

    # 评分 >= 5 视为买入信号
    is_buy = score >= 5

    details = {
        "代码": "", "名称": "",
        "最新价": round(price, 2),
        "5日线": round(ma5, 2),
        "10日线": round(ma10, 2),
        "20日线": round(ma20, 2),
        "60日线": round(ma60, 2),
        "量比": round(volume / vol_ma5, 2) if vol_ma5 and vol_ma5 > 0 else 0,
        "买入评分": score,
        "5日金叉10日": golden_cross_5_10,
        "10日金叉20日": golden_cross_10_20,
        "股价上穿20日": price_cross_above_20,
        "多头排列": bullish_alignment,
        "成交量放大": volume_surge,
    }

    return is_buy, details


# ============================================================
#   微信推送（Server酱）
# ============================================================

def send_wechat(title, content):
    """通过Server酱推送微信消息"""
    if not SERVERCHAN_KEY:
        print("未配置SERVERCHAN_KEY，跳过推送")
        return False
    try:
        import requests
        url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send"
        data = {"title": title, "desp": content}
        r = requests.post(url, data=data, timeout=15)
        result = r.json()
        if result.get("code") == 0:
            print(f"微信推送成功: {title}")
            return True
        else:
            print(f"微信推送失败: {result.get('message', '未知错误')}")
            return False
    except Exception as e:
        print(f"微信推送异常: {e}")
        return False


# ============================================================
#   主流程
# ============================================================

def main():
    print("=" * 60)
    print("  沪深300买入信号自动扫描")
    print(f"  运行时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print()

    # 1. 获取股票列表
    stock_list = get_stock_list()
    total = len(stock_list)
    print(f"共 {total} 只股票，开始扫描...")
    print()

    # 2. 逐只扫描
    buy_stocks = []
    success = 0
    failed = 0

    for idx, row in stock_list.iterrows():
        code = row["代码"]
        name = row["名称"]
        try:
            df = get_stock_history(code)
            if df is None or len(df) < 80:
                failed += 1
                time.sleep(SLEEP_BETWEEN)
                continue

            success += 1
            df = calc_indicators(df)
            if df is None:
                time.sleep(SLEEP_BETWEEN)
                continue

            is_buy, details = detect_buy_signal(df)
            if is_buy and details:
                details["代码"] = code
                details["名称"] = name
                buy_stocks.append(details)
                print(f"  ✓ [{idx+1}/{total}] {code} {name}  买入评分:{details['买入评分']}  现价:{details['最新价']}")

            time.sleep(SLEEP_BETWEEN)

        except Exception as e:
            failed += 1
            if failed <= 3:
                print(f"  ✗ [{idx+1}/{total}] {code} {name} 错误: {str(e)[:40]}")
            time.sleep(SLEEP_BETWEEN)
            continue

    print()
    print(f"扫描完成：成功 {success} 只，失败 {failed} 只")
    print(f"发现买入信号：{len(buy_stocks)} 只")
    print()

    # 3. 按买入评分排序
    buy_stocks.sort(key=lambda x: x["买入评分"], reverse=True)

    # 4. 生成推送内容
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    if len(buy_stocks) == 0:
        title = f"📊 沪深300买入信号（{now_str}）"
        content = (
            f"**扫描时间**：{now_str}\n\n"
            f"**扫描结果**：共扫描 {total} 只股票，成功 {success} 只\n\n"
            f"**本次未发现符合条件的买入信号。**\n\n"
            f"---\n"
            f"*买入标准：5日金叉10日 + 股价上穿20日 + 多头排列 + 放量*\n"
            f"*每周一、三、五 14:30 自动推送*"
        )
    else:
        title = f"🟢 买入信号：{len(buy_stocks)}只（{now_str}）"
        content = f"**扫描时间**：{now_str}\n\n"
        content += f"**扫描结果**：共扫描 {total} 只，发现买入信号 {len(buy_stocks)} 只\n\n"
        content += "---\n\n"

        for i, s in enumerate(buy_stocks[:20], 1):
            # 信号标签
            tags = []
            if s["5日金叉10日"]: tags.append("金叉")
            if s["股价上穿20日"]: tags.append("上穿20日")
            if s["多头排列"]: tags.append("多头排列")
            if s["成交量放大"]: tags.append("放量")
            tag_str = "、".join(tags) if tags else "趋势向好"

            content += f"**{i}. {s['代码']} {s['名称']}**\n"
            content += f"- 现价：{s['最新价']}元 | 量比：{s['量比']} | 买入评分：{s['买入评分']}\n"
            content += f"- 5日：{s['5日线']} | 10日：{s['10日线']} | 20日：{s['20日线']} | 60日：{s['60日线']}\n"
            content += f"- 信号：{tag_str}\n"
            content += f"- 建议：在{s['最新价']}元附近或回踩20日线({s['20日线']}元)分批建仓，跌破{round(s['20日线']*0.97, 2)}元止损\n\n"

        if len(buy_stocks) > 20:
            content += f"\n*还有 {len(buy_stocks) - 20} 只买入信号股票未列出*\n\n"

        content += "---\n"
        content += "*买入标准：5日金叉10日 + 股价上穿20日 + 多头排列 + 成交量放大*\n"
        content += "*每周一、三、五 14:30 自动推送*\n"
        content += "*⚠️ 仅供参考，不构成投资建议，股市有风险*"

    # 5. 推送微信
    print("正在推送微信...")
    send_wechat(title, content)

    print()
    print("=" * 60)
    print("  任务完成")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"程序出错: {e}")
        traceback.print_exc()
        # 出错也推送一条通知
        if SERVERCHAN_KEY:
            send_wechat("⚠️ 选股程序运行出错", f"错误信息：{str(e)[:200]}\n\n请检查配置。")
