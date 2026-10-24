# workbuddy.md · WorkBuddy 开发对话上下文记录

> 本文件为 WorkBuddy 专项奖励提交材料，记录本项目在腾讯 WorkBuddy 智能体辅助下的开发过程。
> 时间线：2026-10-25 00:16 – 00:46（北京时间）

## 1. 项目背景输入

开发者向 WorkBuddy 提供了「麦当劳程序员创意开发大赛」官方仓库材料（mcd-developer-innovation-challenge-main.zip），包含 README.md、activityGuidelines.md、RANKING.md、CONTEST_DECLARATION.md。WorkBuddy 完成以下分析：

- 校准时间认知偏差：指出报名硬截止为 2026-10-25 23:59（当日），并据此生成单日冲刺倒排计划（M1 19:00 作品完成 / M2 21:00 提交报名 Issue / 23:59 硬截止）。
- 从 RANKING.md 提取进榜门槛：第 100 名为 54 Star，Star 为 0 不进榜。
- 提示报名 Issue 三大避坑点（换行符、Markdown 链接、Public 仓库）与文件清单（README 表格与 activityGuidelines 取并集，含 mcp-config.example.json）。
- 设置 5 个一次性定时提醒（09:00 启动 / 19:00 M1 / 21:00 提 Issue / 11-07 查获奖邮件 / 11-12 领奖信息）。

## 2. 选题决策

WorkBuddy 基于 RANKING.md 竞品分析（前 10 名中 5 个为"省钱/预算"类）建议差异化方向，开发者选定「加班/深夜场景套餐推荐」+「Skill + Python 脚本」形态。

## 3. WorkBuddy 完成的关键开发工作

1. **MCP 客户端**（src/mcd_mcp.py）：纯 Python 标准库实现 MCP Streamable HTTP 客户端，覆盖 initialize 握手、Mcp-Session-Id 会话管理、SSE 与 JSON 双格式响应解析、401/429 错误码友好提示。
2. **真实契约适配**：使用开发者提供的 MCP Token 调用 `tools/list`，导出全部 35 个工具的真实 inputSchema（examples/tools-dump.json），发现并修正了两处错误假设：
   - `query-nearby-stores` 实际必填 `beType + searchType`（searchType=2 时还需 `city + keyword`），而非 `address`；
   - `calculate-price` 返回价格单位为"分"，需除以 100 展示。
3. **推荐引擎**（src/advisor.py）：按官方 beType→orderType/beCode 契约构造参数；展平 `query-meals` 的 `data.categories[].meals[]` 嵌套结构；解析 `list-nutrition-foods` 的自定义文本格式（`[160]{productName,...,energyKcal,...}:`）建立 160 行营养索引；套餐热量按默认组合单品热量求和估算；解析门店 `reservationTimeOptions` 得出"门店当前供餐时段"。
4. **端到端真机验证**：2026-10-25 00:45 完整跑通 21 次真实 MCP 调用（0 失败），输出三个互斥推荐方案（最省心 ¥11.9/328 kcal、最省钱 ¥26.9/436 kcal、最轻负担 ¥29.9/436 kcal），并识别出门店供餐时段为"宵夜"。
5. **合规把关**：CONTEST_DECLARATION.md 原样复制未改动；mcp-config.example.json 仅含环境变量占位符；push 前执行 `Bearer`/`Authorization` 全局扫描；Token 仅通过环境变量注入，未写入任何仓库文件。

## 4. 产出物清单

- 可运行源代码：main.py、src/mcd_mcp.py、src/advisor.py（零第三方依赖，Python 3.9+）
- 文档：README.md、MCP_INTEGRATION.md、SKILL.md、mcp-config.example.json
- 真实调用证据：examples/tools-dump.json（35 个工具 schema）、examples/raw-demo.json（完整推荐结果含调用轨迹）

## 5. 声明

以上过程由腾讯 WorkBuddy 智能体辅助完成，代码经开发者确认后提交；麦当劳 MCP 数据版权归麦当劳中国所有，本项目仅通过官方 MCP 接口按服务条款调用。
