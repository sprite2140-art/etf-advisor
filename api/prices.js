// api/prices.js
// 这个文件运行在 Vercel 服务器上，负责从新浪财经抓取实时 ETF 价格
// 因为浏览器直接请求新浪会被拦截（CORS），所以需要这个中间层

const https = require('https');

module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Cache-Control', 's-maxage=15, stale-while-revalidate'); // 缓存 15 秒

  // 你的三只 ETF 代码（sz = 深交所）
  const codes = 'sz159869,sz161125,sz159583';
  const url = `https://hq.sinajs.cn/list=${codes}`;

  try {
    const raw = await fetch_data(url);
    const prices = parse(raw);
    res.status(200).json({ success: true, data: prices });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
};

// 请求新浪财经数据
function fetch_data(url) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, {
      headers: {
        'Referer': 'https://finance.sina.com.cn',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
      },
    }, (res) => {
      // 新浪返回 GBK 编码，这里转为字符串
      const chunks = [];
      res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    });
    req.on('error', reject);
    req.setTimeout(8000, () => { req.destroy(); reject(new Error('请求超时')); });
  });
}

// 解析新浪财经返回的数据格式：
// var hq_str_sz159869="游戏ETF,开盘,昨收,现价,最高,最低,...";
function parse(raw) {
  const result = {};
  for (const line of raw.split('\n')) {
    const match = line.match(/hq_str_(\w+)="([^"]+)"/);
    if (!match || !match[2]) continue;

    const code   = match[1];
    const fields = match[2].split(',');
    if (fields.length < 6) continue;

    const current   = parseFloat(fields[3]);
    const prevClose = parseFloat(fields[2]);
    if (!current || !prevClose) continue;

    result[code] = {
      name:      fields[0],
      current,
      prevClose,
      open:  parseFloat(fields[1]),
      high:  parseFloat(fields[4]),
      low:   parseFloat(fields[5]),
    };
  }
  return result;
}
