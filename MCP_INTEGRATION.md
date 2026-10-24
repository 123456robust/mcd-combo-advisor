# MCP 集成说明

## 1. 使用的 MCP Server

| 项 | 值 |
|---|---|
| 提供方 | 麦当劳中国（M-China） |
| 接入地址 | `https://mcp.mcd.cn` |
| 传输协议 | MCP **Streamable HTTP** |
| 鉴权方式 | 请求头 `Authorization: Bearer <MCP_TOKEN>`，Token 从环境变量 `MCD_MCP_TOKEN` 读取 |
| 限流 | 每个 Token 每分钟最多 600 次请求，超限返回 429 |
| 错误码 | 401 Token 无效/过期；429 触发限流 |

配置示例见 [`mcp-config.example.json`](./mcp-config.example.json)，**其中只包含环境变量占位符，不含任何真实凭据**。

## 2. 实际调用的 Tool

本项目不是"提到 MCP"而已，以下 7 个工具构成完整决策链路，全部来自麦当劳 MCP Server 官方工具列表：

| # | Tool 名称 | 在本项目中的作用 |
|:--:|---|---|
| 1 | `now-time-info` | 获取当前完整时间，判定处于早餐/午市/下午茶/晚市/夜宵/深夜哪个时段，并据此切换推荐策略 |
| 2 | `query-nearby-stores` | 按用户位置查询附近可用门店，作为后续取菜单与取券的门店上下文 |
| 3 | `query-meals` | 拉取该门店**此刻真实在售**的餐品列表，避免推荐已售罄或非该门店供应的餐品 |
| 4 | `query-meal-detail` | 展开套餐组成与可替换项，用于判断套餐实际内容 |
| 5 | `list-nutrition-foods` | 获取餐品营养成分，用于"深夜轻负担"排序与热量展示 |
| 6 | `query-store-coupons` | 查询当前门店下可用优惠券，作为价格优化的入参 |
| 7 | `calculate-price` | 计算商品金额、配送费、优惠金额与应付总价，给出真实到手价 |

> 参数构造依据真实 `inputSchema`：开发时通过 `tools/list` 导出全部 35 个工具的真实参数定义（见 `examples/tools-dump.json`），再按官方契约硬编码构造（beType→orderType/beCode 配对、价格单位"分"转"元"）。可用 `python main.py --dump-tools` 随时复核。

## 3. 调用流程

```
用户输入：位置 + 预算 + 人数 + 偏好
        │
        ▼
  now-time-info          ──→ 判断时段（深夜 / 夜宵 / 正餐 / 早餐）
        │
        ▼
  query-nearby-stores    ──→ 取最近门店作为上下文
        │
        ▼
  query-meals            ──→ 该门店当前在售菜单
        │
        ├──────────────→ query-meal-detail   展开套餐组成
        │
        ▼
  list-nutrition-foods   ──→ 建立热量索引，深夜场景按 ≤650 kcal 加权
        │
        ▼
  query-store-coupons    ──→ 当前门店可用券
        │
        ▼
  calculate-price        ──→ 商品金额 + 配送费 − 优惠 = 应付总价
        │
        ▼
  输出 3 个方案（最省心 / 最省钱 / 最轻负担）+ 价格 + 热量 + 理由
```

任一环节失败会**跳过并继续**，最终结果标注缺失来源，不会中断整个推荐（`src/advisor.py::Advisor._call`）。

## 4. 业务价值

- **对消费者**：加班与深夜是最容易"随便点、点贵、点胖"的场景。把时间、地点、预算、热量四个维度一起算，直接给出可执行结论，而不是一份菜单。
- **对麦当劳 MCP 生态**：演示了一条跨 7 个工具的真实编排链路，覆盖时间、门店、菜单、套餐详情、营养、优惠券、计价七类能力，可作为 MCP 组合调用的参考实现。
- **合规性**：营业时间、在售状态、价格一律以 MCP 返回与麦当劳官方渠道为准，不缓存、不臆造；输出末尾固定附带免责提示。

## 5. 复现方式

```bash
export MCD_MCP_TOKEN='你的Token'
python main.py --dump-tools                                   # 核对真实工具 schema
python main.py --city "上海" --keyword "人民广场" --budget 40 --people 1
python main.py --city "上海" --keyword "人民广场" --save-raw examples/raw-demo.json   # 保存原始响应
```
