<div align="center">

# 🍔 麦麦加班套餐助手

**加班到十点，附近还能吃什么？告诉它你在哪、几点、预算多少，它查麦当劳真实接口，告诉你此刻这家店真能点到什么、多少钱、多少卡。**

[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/McDonald's%20MCP-7%20tools%20chained-FFC72C)](https://mcp.mcd.cn)
[![Dependencies](https://img.shields.io/badge/dependencies-0%20(stdlib%20only)-4CAF50)](./src)
[![Contest](https://img.shields.io/badge/McDonald's-Dev%20Innovation%20Challenge-D62327)](https://github.com/M-China-Official/mcd-developer-innovation-challenge)

</div>

---

## ✨ 功能亮点

| | |
|---|---|
| 🕐 **按「此刻」推荐** | 先用 `now-time-info` 取服务器时间判时段，再读门店返回的**真实供餐时段**（宵夜 / 早餐 / 午餐 / 下午茶 / 夜市），不是按钟点猜 |
| 🏪 **只推真能点到的** | 查附近门店的 `businessStatus` 营业状态，再用 `query-meals` 拉**当前在售**餐品——已打烊的和售罄的不会出现 |
| 💰 **实付价，不是标价** | 价格走 `calculate-price` 真实计价（接口返回"分"，已换算为元） |
| 🔥 **热量可估算** | 用 `list-nutrition-foods` 的 160 条真实营养数据，按套餐默认组合求和 |
| 🎯 **给三个互斥方案** | 最省心 / 最省钱 / 最轻负担，自己挑，不替你做"最优解" |
| 🛡️ **不编数据** | 接口没返回的字段就明说"以官方渠道为准"；某个调用失败就跳过并标注，整条链不断 |

## 📦 安装

前置：去 [mcp.mcd.cn](https://mcp.mcd.cn) 用手机号登录 → 右上角进控制台 → 点激活 → 复制 Token。

```bash
git clone https://github.com/123456robust/mcd-combo-advisor.git
cd mcd-combo-advisor

# 零第三方依赖，纯标准库，Python 3.9+ 直接跑
export MCD_MCP_TOKEN='你的Token'          # PowerShell: $env:MCD_MCP_TOKEN='你的Token'
python main.py --dump-tools               # 先把接口真实字段打出来看看
```

## 🚀 用法

```bash
python main.py --city "上海" --keyword "人民广场" --budget 40
```

| 参数 | 说明 | 默认 |
|---|---|---|
| `--city` | 城市名 | 上海 |
| `--keyword` | 地标 / 商圈关键词 | 人民广场 |
| `--budget` | 预算（元） | 不限 |
| `--people` | 人数 | 1 |
| `--save-raw` | 把原始返回存成 JSON | — |
| `--dump-tools` | 打印全部 33 个工具的真实 schema | — |

### 真实输出（2026-10-25 00:45 实测，非样例）

```
==========================================================
  麦麦加班套餐推荐  |  当前 00:45 · 深夜时段
==========================================================
位置：上海 · 人民广场    场景：到店自取
命中门店：5 家 | 在售餐品：87 项 | 可用券：0 张
参考门店：麦当劳上海黄浦华旭国际大厦餐厅
时段建议：严格轻负担，避免咖啡因与碳酸
门店当前供餐时段：宵夜

推荐方案

  1. 最省心 · 蘸酱炸鸡
     麦麦脆汁鸡-琵琶腿 + 北美招牌牧场酱
     ¥11.9 | 328 kcal
     理由：深夜时段推荐：约 328 kcal，深夜轻负担；¥11.9；人气热卖
     预算：在预算内（11.90 元）

  2. 最省钱 · 龙焰鸡腿堡三件套
     龙焰鸡腿堡 + 中薯条 + 可乐中杯
     ¥26.9 | 436 kcal
     理由：当前在售里实付最低（¥26.9）

  3. 最轻负担 · 龙焰芝士棒鸡腿堡三件套
     龙焰芝士棒鸡腿堡 + 中薯条 + 可乐中杯
     ¥29.9 | 436 kcal
     理由：热量最低（约 436 kcal），适合深夜时段

MCP 调用轨迹
  [ OK ] now-time-info          获取当前服务器时间，判断所处时段  dict
  [ OK ] query-nearby-stores    按位置查询附近可点餐门店（到店自取）  dict
  [ OK ] query-meals            查询该门店当前可售餐品  dict
  [ OK ] list-nutrition-foods   获取餐品营养成分表  dict
  [ OK ] query-meal-detail      展开套餐 9900015183 组成  dict
  [ OK ] calculate-price        计算 9900015183 实付价  dict
  ...（共 21 次真实调用，0 失败）
```

## 🔗 MCP 工具链

```
now-time-info → query-nearby-stores → query-meals → query-meal-detail
                                          ↓
                        list-nutrition-foods → query-store-coupons → calculate-price
```

| 工具 | 拿什么 |
|---|---|
| `now-time-info` | 服务器当前时间 → 判时段 |
| `query-nearby-stores` | 附近门店 + 营业状态 + **供餐时段配置** |
| `query-meals` | 该门店此刻在售餐品（只返回编码） |
| `query-meal-detail` | 编码 → 名称 + 套餐默认组合 |
| `list-nutrition-foods` | 160 条真实营养数据 |
| `query-store-coupons` | 门店可用券 |
| `calculate-price` | **实付价**（单位：分） |

详见 [MCP_INTEGRATION.md](./MCP_INTEGRATION.md)。

## 📊 数据来源说明

| 展示内容 | 来源 | 准确度 |
|---|---|---|
| 门店、营业状态、供餐时段 | `query-nearby-stores` | 接口实时返回 |
| 在售餐品 | `query-meals` | 接口实时返回 |
| 价格 | `calculate-price` | 实付价，精确到分 |
| 热量 | `list-nutrition-foods` | **按默认组合估算**，换配菜就不准 |
| 时段策略阈值 | 本项目自定义 | 经验值，非营养学结论 |

## 🛠️ 踩到的坑

官方文档只给了工具名和一句描述，**没给入参**。第一次调错了两处：门店查询要 `city` + `keyword` + `beType` + `searchType`（不是我以为的地址字符串）；价格单位是**分**（第一版输出 ¥3450，看着像在卖显卡）。

后来不猜了——代码先 `tools/list` 拉真实 schema，再按 schema 名字匹配填参，字段名是 `storeCode` 还是 `store_code` 都能对上。

还有个没想到的事：菜单接口只返回一串编码，名字要再调一次 detail，价格要再调 calculate-price。那 21 次调用，大部分是在"把编码换成信息"。

## ⚠️ 还没做好的地方

- 热量是估算，换成大薯条或多加酱就不准
- 优惠券逻辑没真跑通过（测试门店凌晨返回 0 张券）
- 只支持到店自取，外送分支留了参数位没做完
- 650 kcal 阈值是我拍的，没有科学依据

## 📁 目录

```
mcd-combo-advisor/
├── main.py                     命令行入口
├── src/
│   ├── mcd_mcp.py              MCP Streamable HTTP 客户端（纯标准库）
│   └── advisor.py              时段策略 + 评分 + 方案生成
├── SKILL.md                    Skill 定义
├── MCP_INTEGRATION.md          用了哪些 MCP 工具、怎么串的
├── mcp-config.example.json     配置示例（已脱敏，仅环境变量占位符）
├── CONTEST_DECLARATION.md      参赛声明（官方原件，未改动）
└── .gitignore
```

## 👤 谁会用到

- 加班到非正餐时段、站在路边不知道还能点什么的人
- 想吃夜宵但明天要体检、想看一眼热量的
- 想看看麦当劳 MCP 那 33 个工具怎么串起来的开发者

---

## 免责声明

麦当劳程序员节创意开发大赛参赛作品，个人独立开发，**非麦当劳官方产品**。输出仅供参考，不构成营养建议；餐品、价格与供应状态以麦当劳官方渠道实时结果为准。
