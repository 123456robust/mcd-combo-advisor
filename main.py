# -*- coding: utf-8 -*-
"""mcd-combo-advisor 命令行入口。

常用命令
--------
    # 1) 拿到 Token 后先 dump 真实工具 schema（用于核对参数名）
    python main.py --dump-tools

    # 2) 正式推荐（到店自取场景）
    python main.py --city "上海" --keyword "人民广场" --budget 40 --people 1

    # 3) 得来速场景
    python main.py --city "上海" --keyword "虹桥机场" --be-type 5

    # 4) 保存原始响应，作为 README / MCP_INTEGRATION.md 的真实调用证据
    python main.py --city "上海" --keyword "人民广场" --save-raw examples/raw-demo.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from advisor import BE_TYPE_NAMES, Advisor  # noqa: E402
from mcd_mcp import McpError, connect  # noqa: E402


def dump_tools(client) -> int:
    tools = client.list_tools()
    payload = [
        {
            "name": tool.get("name"),
            "description": tool.get("description"),
            "required": (tool.get("inputSchema") or {}).get("required", []),
            "properties": list((tool.get("inputSchema") or {}).get("properties", {}).keys()),
        }
        for tool in tools
    ]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\n共 {len(tools)} 个工具，已列出真实参数名。", file=sys.stderr)
    return 0


def render(result: dict) -> None:
    now = result["now"]
    query = result["query"]
    print("\n" + "=" * 58)
    print(f"  麦麦加班套餐推荐  |  当前 {now['clock']} · {now['slot']}")
    print("=" * 58)
    print(f"位置：{query['city']} · {query['keyword']}    "
          f"场景：{query['beTypeName']}")
    print(f"命中门店：{result['store_count']} 家 | 在售餐品：{result['menu_size']} 项 "
          f"| 可用券：{result['coupon_count']} 张")
    if result["store"]:
        store = result["store"]
        name = (store.get("storeName") or store.get("name")
                or store.get("storeAddr") or "最近门店")
        print(f"参考门店：{name}")

    if not result["plans"]:
        print("\n未拿到在售餐品。可能原因：")
        print("  1) 附近无该类型门店（试试 --be-type 5 得来速）")
        print("  2) 位置关键词太模糊（换个更精确的街道/地标）")
        print("  3) MCP 返回结构与预期不同，用 --save-raw 保存后检查")
    else:
        print(f"时段建议：{now['hint']}")
        if result.get("serving_period"):
            print(f"门店当前供餐时段：{result['serving_period']}")
        print("\n推荐方案")
        for idx, plan in enumerate(result["plans"], 1):
            price = f"¥{plan['price']:g}" if plan["price"] is not None else "价格未知"
            kcal = f"{plan['kcal']:.0f} kcal" if plan["kcal"] is not None else "热量未知"
            print(f"\n  {idx}. {plan['title']}")
            print(f"     {plan['combo']}")
            print(f"     {price} | {kcal}")
            print(f"     理由：{plan['why']}")
            if "within_budget" in plan:
                flag = "在预算内" if plan["within_budget"] else "超出预算"
                print(f"     预算：{flag}（{plan['est_total']:.2f} 元）")

    print("\nMCP 调用轨迹")
    for step in result["trace"]:
        mark = {"ok": "[ OK ]", "failed": "[FAIL]", "skipped": "[SKIP]"}.get(
            step["status"], "[ -- ]")
        extra = step.get("reason", step.get("response_type", ""))
        print(f"  {mark} {step['tool']:<22} {step['purpose']}  {extra}")
    print(f"\n{result['notice']}\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="麦当劳加班/深夜套餐推荐助手（基于麦当劳 MCP）")
    parser.add_argument("--city", help="城市名，如：上海（searchType=2 时必填）")
    parser.add_argument("--keyword", help="位置关键词，如：人民广场（searchType=2 时必填）")
    parser.add_argument("--budget", type=float, default=None, help="预算上限（元）")
    parser.add_argument("--people", type=int, default=1, help="用餐人数")
    parser.add_argument("--prefer", choices=["light", "full"], default="light",
                        help="light=轻负担（默认），full=吃饱")
    parser.add_argument("--be-type", type=int, default=1, choices=[1, 5, 2, 6],
                        help="1=到店自取(默认) 5=得来速 2=麦乐送 6=团餐")
    parser.add_argument("--dump-tools", action="store_true",
                        help="输出真实 MCP 工具 schema 后退出")
    parser.add_argument("--save-raw", metavar="PATH", help="把完整结果保存为 JSON")
    args = parser.parse_args()

    if not args.dump_tools and not (args.city and args.keyword):
        parser.error("需要同时提供 --city 和 --keyword；或用 --dump-tools 查看工具列表")

    try:
        client = connect()
    except McpError as exc:
        print(f"连接失败：{exc}", file=sys.stderr)
        return 2

    try:
        if args.dump_tools:
            return dump_tools(client)

        advisor = Advisor(client, be_type=args.be_type)
        result = advisor.recommend(
            city=args.city,
            keyword=args.keyword,
            budget=args.budget,
            people=args.people,
            prefer=args.prefer,
        )
        render(result)

        if args.save_raw:
            directory = os.path.dirname(os.path.abspath(args.save_raw))
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(args.save_raw, "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=2)
            print(f"原始响应已保存：{args.save_raw}")
        return 0
    except McpError as exc:
        print(f"调用失败：{exc}", file=sys.stderr)
        return 3
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
