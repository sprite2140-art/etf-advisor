#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETF AI Analysis Script
Fetches news + price data, calls DeepSeek API, saves analysis.json
Runs via GitHub Actions at 9:30 and 15:30 CST on trading days
"""
import json, os, time, requests
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
now = datetime.now(CST)
today = now.strftime('%Y-%m-%d')
now_str = now.strftime('%Y-%m-%d %H:%M')

API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')

HOLDINGS = [
    {'code': 'sz159869', 'name': '游戏ETF',     'shares': 55000, 'cost': 1.198,
     'keywords': ['游戏ETF', '版号', '游戏行业']},
    {'code': 'sz161125', 'name': '标普500LOF',  'shares': 33100, 'cost': 2.795,
     'keywords': ['标普500', '美联储', '美股']},
    {'code': 'sz159583', 'name': '通信设备ETF', 'shares': 90600, 'cost': 1.267,
     'keywords': ['通信设备ETF', '5G', '华为中兴']},
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://www.eastmoney.com/',
}

# ─── Load prices ──────────────────────────────────────────────────────────────
prices = {}
try:
    with open('prices.json', encoding='utf-8') as f:
        raw = json.load(f)
    prices = raw.get('data', {}) if raw.get('success') else {}
    print(f'Loaded prices for {len(prices)} codes')
except Exception as e:
    print(f'prices.json load error: {e}')

def get_price(code):
    p = prices.get(code, {})
    cur  = p.get('current') or p.get('cur') or 0
    prev = p.get('prevClose') or p.get('prev') or 0
    if cur and prev:
        return {'price': cur, 'prev': prev, 'change_pct': (cur - prev) / prev * 100}
    return None

# ─── Fetch news from Eastmoney ────────────────────────────────────────────────
def fetch_news(code_num, keyword, n=4):
    """Try stock-specific news, fallback to keyword search"""
    for params in [
        {'client': 'web', 'type': '1', 'mTypeAndCode': f'0,{code_num}', 'pageSize': n, 'pageIndex': 1},
        {'client': 'web', 'type': '1', 'keyword': keyword,             'pageSize': n, 'pageIndex': 1},
    ]:
        try:
            r = requests.get(
                'https://np-listapi.eastmoney.com/comm/web/getNPNewsList',
                params={**params, '_': int(time.time() * 1000)},
                headers=HEADERS, timeout=10
            )
            items = r.json().get('data', {}).get('list', [])
            if items:
                return [{'title': i.get('title', ''), 'time': i.get('showtime', '')} for i in items[:n]]
        except Exception as e:
            print(f'News fetch error ({keyword}): {e}')
    return []

# ─── Build data for each holding ─────────────────────────────────────────────
auto_events  = []
holdings_out = []
prompt_parts = []

for h in HOLDINGS:
    code_num   = h['code'][2:]
    price_info = get_price(h['code'])
    news       = fetch_news(code_num, h['keywords'][0], 4)

    # Auto-event when daily move ≥ 2%
    if price_info and abs(price_info['change_pct']) >= 2.0:
        chg = price_info['change_pct']
        auto_events.append({
            'id':         f'auto_{h["code"]}_{today.replace("-","")}',
            'title':      f'{h["name"]} 今日{"下跌" if chg < 0 else "上涨"} {abs(chg):.2f}%',
            'dir':        'bear' if chg < 0 else 'bull',
            'code':       h['code'],
            'name':       h['name'],
            'change_pct': round(chg, 2),
            'date':       today,
            'time':       now.strftime('%H:%M'),
            'auto':       True,
        })

    pnl_pct   = ((price_info['price'] - h['cost']) / h['cost'] * 100) if price_info else None
    chg_str   = (f"{price_info['change_pct']:+.2f}%") if price_info else '无数据'
    pnl_str   = (f"{pnl_pct:+.2f}%") if pnl_pct is not None else '未知'
    news_text = '\n'.join([f'  · {n["title"]}' for n in news]) if news else '  暂无相关新闻'

    prompt_parts.append(
        f'【{h["name"]}（{code_num}）】\n'
        f'  今日涨跌：{chg_str}\n'
        f'  浮盈亏：{pnl_str}\n'
        f'  相关新闻：\n{news_text}'
    )

    holdings_out.append({
        'code':       h['code'],
        'name':       h['name'],
        'price':      price_info['price'] if price_info else None,
        'change_pct': round(price_info['change_pct'], 2) if price_info else None,
        'pnl_pct':    round(pnl_pct, 2) if pnl_pct is not None else None,
        'news':       news,
    })

# ─── Call DeepSeek API ────────────────────────────────────────────────────────
def call_deepseek(parts):
    if not API_KEY:
        return '未配置 DEEPSEEK_API_KEY，请在 GitHub → Settings → Secrets 中添加。'

    prompt = (
        '你是我的 ETF 投资顾问，我是金融小白，语言要通俗易懂。\n'
        '以下是我今天三只持仓 ETF 的数据和相关新闻：\n\n'
        + '\n\n'.join(parts)
        + '\n\n请分别针对每只 ETF：\n'
          '1. 用1-2句话解释今天涨跌的可能原因（结合新闻）\n'
          '2. 给一个操作建议：持有 / 加仓 / 减仓 / 观察\n'
          '3. 需要关注的1个风险点\n\n'
          '最后写一句整体建议。要直接给结论，不废话。'
    )

    try:
        r = requests.post(
            'https://api.deepseek.com/chat/completions',
            headers={'Authorization': f'Bearer {API_KEY}', 'Content-Type': 'application/json'},
            json={
                'model': 'deepseek-chat',
                'messages': [
                    {'role': 'system', 'content': '你是简洁直接的 ETF 投资顾问，擅长 A 股和美股 ETF，回答通俗易懂。'},
                    {'role': 'user',   'content': prompt},
                ],
                'max_tokens': 900,
                'temperature': 0.3,
            },
            timeout=60,
        )
        return r.json()['choices'][0]['message']['content']
    except Exception as e:
        print(f'DeepSeek error: {e}')
        return f'AI 分析暂时不可用，请稍后刷新重试。（错误：{str(e)[:80]}）'

print('Calling DeepSeek API...')
ai_text = call_deepseek(prompt_parts)

# ─── Save output ──────────────────────────────────────────────────────────────
output = {
    'generated_at': now_str,
    'auto_events':  auto_events,
    'holdings':     holdings_out,
    'ai_analysis':  ai_text,
}

with open('analysis.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f'✅ analysis.json saved at {now_str}')
print(f'   Auto events: {len(auto_events)}')
print(f'   AI preview:  {ai_text[:120]}...')
