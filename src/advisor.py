# -*- coding: utf-8 -*-
"""加班 / 深夜场景的麦当劳套餐推荐引擎。

所有参数与解析均按麦当劳 MCP 真实返回结构编写（2026-10-25 实测）：

    now-time-info        → 服务器当前时间，判断所处时段
    query-nearby-stores  → data[]: storeCode/storeName/address/distance/
                           businessStatus/businessStartTime/businessEndTime/
                           reservationTimeOptions[].reservationOptionText
    query-meals          → data.categories[].meals[]: 仅 code + tags（无名称价格）
    query-meal-detail    → data: name/rounds[].choices[]（isDefault/diffPrice）
                           套餐本身无总价，只有换购差价
    list-nutrition-foods → data 为文本: [N]{productName,...,energyKcal,...}:
                           每行 "名称,null,kJ,kcal,蛋白质,脂肪,碳水,钠,钙"
    query-store-coupons  → 当前门店可用券
    calculate-price      → data.price 单位为分（展示需 /100），
                           data.productList[].productName

关键契约（tools/list 官方描述）：
    到店自取 beType=1 → orderType=1，不传 beCode
    得来速   beType=5 → orderType=1，必传 beCode
    麦乐送   beType=2 → orderType=2，必传 beCode
    团餐     beType=6 → orderType=2，必传 beCode
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from mcd_mcp import McpClient, McpError

LATE_NIGHT_KCAL_LIMIT = 650
LATE_NIGHT_AVOID = ("美式", "拿铁", "咖啡", "可乐", "雪碧", "气泡")

# 候选餐品的分类优先级（靠前的分类优先取样）
PRIORITY_CATEGORIES = ("精选单人餐", "人气热卖", "随心配", "小食拼盘")
MAX_CANDIDATES = 8  # detail + price 各调一次，控制总调用量（限流 600/min）

TIME_SLOTS = [
    (5, 10, "早餐时段", "优先早餐类组合，配一杯热饮"),
    (10, 14, "午市时段", "正餐份量，优先超值午餐组合"),
    (14, 17, "下午茶时段", "小食配饮料，控制总热量"),
    (17, 21, "晚市时段", "正餐份量，可以放开一点"),
    (21, 23, "夜宵时段", "偏轻负担，避免高油高钠"),
    (23, 24, "深夜时段", "严格轻负担，避免咖啡因与碳酸"),
    (0, 5, "深夜时段", "严格轻负担，避免咖啡因与碳酸"),
]

ORDER_TYPE_OF = {1: 1, 5: 1, 2: 2, 6: 2}
BE_TYPE_NAMES = {1: "到店自取", 5: "得来速车道", 2: "麦乐送", 6: "企业团餐"}


def order_type_of(be_type: int) -> int:
    return ORDER_TYPE_OF.get(be_type, 1)


class Advisor:
    """把 MCP 原始能力编排成"此刻该吃什么"的答案。"""

    def __init__(self, client: McpClient, be_type: int = 1) -> None:
        self.client = client
        self.be_type = be_type
        self.order_type = order_type_of(be_type)
        self.trace: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # 基础设施
    # ------------------------------------------------------------------
    def _call(self, tool: str, arguments: Dict[str, Any], purpose: str) -> Any:
        record: Dict[str, Any] = {"tool": tool, "purpose": purpose, "arguments": arguments}
        try:
            data = self.client.call_tool(tool, arguments)
        except McpError as exc:
            record.update(status="failed", reason=str(exc))
            self.trace.append(record)
            return None
        record.update(status="ok", response_type=type(data).__name__)
        self.trace.append(record)
        return data

    def _data(self, raw: Any) -> Any:
        """剥掉 {success, code, message, data} 信封。"""
        if isinstance(raw, dict) and isinstance(raw.get("data"), (dict, list, str)):
            return raw["data"]
        return raw

    def _store_args(self, store_code: str, be_code: Optional[str] = None) -> Dict[str, Any]:
        args: Dict[str, Any] = {
            "storeCode": store_code,
            "orderType": self.order_type,
            "beType": self.be_type,
        }
        if self.be_type != 1 and be_code:
            args["beCode"] = be_code
        return args

    # ------------------------------------------------------------------
    # 步骤 1：当前时间
    # ------------------------------------------------------------------
    def now(self) -> Dict[str, Any]:
        raw = self._call("now-time-info", {}, "获取当前服务器时间，判断所处时段")
        return self.parse_time(raw)

    @staticmethod
    def parse_time(raw: Any) -> Dict[str, Any]:
        text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
        match = re.search(r"(\d{1,2})\s*[:：]\s*(\d{2})", text)
        if match:
            hour, minute = int(match.group(1)), int(match.group(2))
        else:
            current = datetime.now()
            hour, minute = current.hour, current.minute
        slot, hint = "正餐时段", "常规推荐"
        for start, end, name, tip in TIME_SLOTS:
            if start <= hour < end:
                slot, hint = name, tip
                break
        return {
            "hour": hour, "minute": minute, "clock": f"{hour:02d}:{minute:02d}",
            "slot": slot, "hint": hint,
            "is_late_night": hour >= 21 or hour < 5,
        }

    # ------------------------------------------------------------------
    # 步骤 2：附近门店（含真实营业状态与供餐时段）
    # ------------------------------------------------------------------
    def find_stores(self, city: str, keyword: str) -> List[Dict[str, Any]]:
        raw = self._call(
            "query-nearby-stores",
            {"beType": self.be_type, "searchType": 2, "city": city, "keyword": keyword},
            f"按位置查询附近可点餐门店（{BE_TYPE_NAMES.get(self.be_type, self.be_type)}）",
        )
        return self._as_list(self._data(raw))

    @staticmethod
    def _as_list(raw: Any) -> List[Dict[str, Any]]:
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]
        if isinstance(raw, dict):
            for key in ("stores", "list", "items", "records", "data"):
                value = raw.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
            return [raw] if raw else []
        return []

    @staticmethod
    def parse_serving_periods(option_text: str) -> List[Dict[str, str]]:
        """解析 '宵夜(00:00至04:45,22:14至23:59)，早餐(05:14至10:15)' 这类文本。"""
        periods: List[Dict[str, str]] = []
        for name, start, end in re.findall(
                r"([\u4e00-\u9fffA-Za-z]+)\((\d{1,2}:\d{2})至(\d{1,2}:\d{2})", option_text or ""):
            periods.append({"name": name, "start": start, "end": end})
        return periods

    @staticmethod
    def current_period(periods: List[Dict[str, str]], hour: int, minute: int) -> Optional[str]:
        minutes_now = hour * 60 + minute
        for period in periods:
            start = period["start"].split(":")
            end = period["end"].split(":")
            start_m = int(start[0]) * 60 + int(start[1])
            end_m = int(end[0]) * 60 + int(end[1])
            if start_m <= end_m:
                if start_m <= minutes_now <= end_m:
                    return period["name"]
            else:  # 跨午夜，如宵夜 00:00 至 04:45 / 22:14 至 23:59
                if minutes_now >= start_m or minutes_now <= end_m:
                    return period["name"]
        return None

    # ------------------------------------------------------------------
    # 步骤 3：菜单（展平 categories[].meals[]）
    # ------------------------------------------------------------------
    def menu(self, store_code: str, be_code: Optional[str] = None) -> List[Dict[str, Any]]:
        raw = self._call("query-meals", self._store_args(store_code, be_code),
                         "查询该门店当前可售餐品")
        return self._flatten_menu(self._data(raw))

    @staticmethod
    def _flatten_menu(data: Any) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        if not isinstance(data, dict):
            return items
        for category in data.get("categories", []) or []:
            if not isinstance(category, dict):
                continue
            cat_name = str(category.get("name", "")).replace("\n", "").strip()
            for meal in category.get("meals", []) or []:
                if isinstance(meal, dict) and meal.get("code"):
                    entry = dict(meal)
                    entry["category"] = cat_name
                    items.append(entry)
        return items

    @staticmethod
    def pick_candidates(flat_menu: List[Dict[str, Any]],
                        limit: int = MAX_CANDIDATES) -> List[Dict[str, Any]]:
        """按分类优先级挑选候选，同 code 去重。"""
        seen: set = set()
        picked: List[Dict[str, Any]] = []
        for cat_name in PRIORITY_CATEGORIES:
            for item in flat_menu:
                if item.get("category") == cat_name and item["code"] not in seen:
                    seen.add(item["code"])
                    picked.append(item)
                    if len(picked) >= limit:
                        return picked
        for item in flat_menu:
            if item["code"] not in seen:
                seen.add(item["code"])
                picked.append(item)
                if len(picked) >= limit:
                    break
        return picked

    # ------------------------------------------------------------------
    # 步骤 4：套餐详情
    # ------------------------------------------------------------------
    def meal_detail(self, store_code: str, code: str, be_code: Optional[str] = None) -> Any:
        args = self._store_args(store_code, be_code)
        args["code"] = code
        return self._call("query-meal-detail", args, f"展开套餐 {code} 组成")

    # ------------------------------------------------------------------
    # 步骤 5：营养（自定义文本格式解析）
    # ------------------------------------------------------------------
    def nutrition(self) -> Optional[str]:
        raw = self._call("list-nutrition-foods", {}, "获取餐品营养成分表")
        data = self._data(raw)
        return data if isinstance(data, str) else None

    @staticmethod
    def parse_nutrition(text: Optional[str]) -> Dict[str, float]:
        """解析 '名称,null,kJ,kcal,蛋白质,脂肪,碳水,钠,钙' 逐行文本。"""
        index: Dict[str, float] = {}
        if not text:
            return index
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("[") or line.startswith("{"):
                continue
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 4:
                continue
            try:
                index[parts[0]] = float(parts[3])  # 第 4 列 = energyKcal
            except ValueError:
                continue
        return index

    # ------------------------------------------------------------------
    # 步骤 6：优惠券
    # ------------------------------------------------------------------
    def coupons(self, store_code: str, be_code: Optional[str] = None) -> List[Dict[str, Any]]:
        raw = self._call("query-store-coupons", self._store_args(store_code, be_code),
                         "查询当前门店可用优惠券")
        return self._as_list(self._data(raw))

    # ------------------------------------------------------------------
    # 步骤 7：实付价（单位分 → 元）
    # ------------------------------------------------------------------
    def price(self, store_code: str, code: str, be_code: Optional[str] = None,
              coupon_id: Optional[str] = None) -> Any:
        items = [{"productCode": code, "quantity": 1}]
        if coupon_id:
            items[0]["couponId"] = coupon_id
        args = self._store_args(store_code, be_code)
        args["items"] = items
        return self._call("calculate-price", args, f"计算 {code} 实付价")

    # ------------------------------------------------------------------
    # 候选餐品富化：detail 拿名称/默认组合，price 拿真实总价
    # ------------------------------------------------------------------
    def enrich(self, store_code: str, candidates: List[Dict[str, Any]],
               be_code: Optional[str] = None, kcal_of: Optional[Dict[str, float]] = None
               ) -> List[Dict[str, Any]]:
        kcal_of = kcal_of or {}
        enriched: List[Dict[str, Any]] = []
        for candidate in candidates:
            code = candidate["code"]
            detail_raw = self.meal_detail(store_code, code, be_code)
            detail = self._data(detail_raw)
            if not isinstance(detail, dict):
                continue
            name = str(detail.get("name") or "").strip()
            if not name:
                continue

            price_raw = self.price(store_code, code, be_code)
            price_data = self._data(price_raw)
            price = None
            discount = None
            if isinstance(price_data, dict):
                cents = price_data.get("price") or price_data.get("productPrice")
                if isinstance(cents, (int, float)):
                    price = round(cents / 100, 2)  # 官方说明：分为单位
                    discount = price_data.get("discount")
                    if isinstance(discount, (int, float)) and discount:
                        discount = round(discount / 100, 2)

            defaults = self._default_choices(detail)
            kcal = self._estimate_kcal(defaults, kcal_of)

            enriched.append({
                "name": name,
                "code": code,
                "category": candidate.get("category", ""),
                "price": price,
                "discount": discount,
                "kcal": kcal,
                "defaults": defaults,
                "tags": candidate.get("tags", []),
            })
        return enriched

    @staticmethod
    def _default_choices(detail: Dict[str, Any]) -> List[str]:
        names: List[str] = []
        for round_ in detail.get("rounds", []) or []:
            if not isinstance(round_, dict):
                continue
            for choice in round_.get("choices", []) or []:
                if isinstance(choice, dict) and choice.get("isDefault") == 1:
                    name = str(choice.get("name", "")).strip()
                    if name:
                        names.append(name)
        return names

    @staticmethod
    def _estimate_kcal(defaults: List[str], kcal_of: Dict[str, float]) -> Optional[float]:
        """套餐热量 ≈ 默认组合各单品热量之和（真实营养数据聚合）。"""
        total = 0.0
        found = False
        for name in defaults:
            if name in kcal_of:
                total += kcal_of[name]
                found = True
        return round(total) if found else None

    # ------------------------------------------------------------------
    # 评分与方案
    # ------------------------------------------------------------------
    def _score(self, items: List[Dict[str, Any]], now: Dict[str, Any],
               prefer: str) -> List[Dict[str, Any]]:
        late = now["is_late_night"]
        for item in items:
            reasons: List[str] = []
            score = 50.0
            kcal = item.get("kcal")
            price = item.get("price")

            if kcal is not None:
                if late:
                    if kcal <= LATE_NIGHT_KCAL_LIMIT:
                        score += 25
                        reasons.append(f"约 {kcal:.0f} kcal，深夜轻负担")
                    else:
                        score -= 25
                        reasons.append(f"约 {kcal:.0f} kcal，深夜偏重")
                elif prefer == "light" and kcal <= LATE_NIGHT_KCAL_LIMIT:
                    score += 10
                    reasons.append("热量适中")
            if late and any(word in item["name"] for word in LATE_NIGHT_AVOID):
                score -= 20
                reasons.append("含咖啡因/碳酸，深夜不友好")
            if price is not None and price > 0:
                score += max(0.0, 15 - price / 3)
                reasons.append(f"¥{price:g}")
            if item.get("discount"):
                reasons.append(f"已优惠 ¥{item['discount']:g}")
            if item.get("category"):
                reasons.append(item["category"])

            item["score"] = round(score, 1)
            item["reasons"] = reasons or ["当前在售可选"]
        items.sort(key=lambda x: x["score"], reverse=True)
        return items

    def _build_plans(self, ranked: List[Dict[str, Any]], budget: Optional[float],
                     people: int, now: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not ranked:
            return []
        plans: List[Dict[str, Any]] = []
        people = max(1, people)
        used: set = set()

        def pick(predicate=None) -> Optional[Dict[str, Any]]:
            for item in ranked:
                if item["code"] in used:
                    continue
                if predicate and not predicate(item):
                    continue
                used.add(item["code"])
                return item
            return None

        def as_plan(item: Dict[str, Any], title: str, why: str) -> Dict[str, Any]:
            return {
                "title": f"{title} · {item['name']}",
                "combo": " + ".join(item["defaults"]) or item["name"],
                "price": item["price"],
                "kcal": item["kcal"],
                "why": why,
            }

        top = pick()
        if top:
            plans.append(as_plan(
                top, "最省心",
                f"{now['slot']}推荐：{'；'.join(top['reasons'])}"))
        cheap = pick(lambda x: x["price"] is not None)
        if cheap:
            plans.append(as_plan(
                cheap, "最省钱",
                f"当前在售里实付最低（¥{cheap['price']:g}）"))
        light = pick(lambda x: x["kcal"] is not None)
        if light:
            plans.append(as_plan(
                light, "最轻负担",
                f"热量最低（约 {light['kcal']:.0f} kcal），适合{now['slot']}"))

        if budget is not None:
            for plan in plans:
                if plan["price"] is not None:
                    total = round(plan["price"] * people, 2)
                    plan["est_total"] = total
                    plan["within_budget"] = total <= budget
        return plans

    # ------------------------------------------------------------------
    # 总编排
    # ------------------------------------------------------------------
    def recommend(self, city: str, keyword: str, budget: Optional[float] = None,
                  people: int = 1, prefer: str = "light") -> Dict[str, Any]:
        now = self.now()
        stores = self.find_stores(city, keyword)

        store: Dict[str, Any] = {}
        for candidate in stores:
            if candidate.get("businessStatus"):
                store = candidate
                break
        if not store and stores:
            store = stores[0]

        store_code = str(store.get("storeCode")) if store.get("storeCode") else None
        be_code = store.get("beCode")

        periods: List[Dict[str, str]] = []
        options = store.get("reservationTimeOptions") or []
        if options and isinstance(options[0], dict):
            periods = self.parse_serving_periods(options[0].get("reservationOptionText", ""))
        serving = self.current_period(periods, now["hour"], now["minute"]) if periods else None

        flat_menu = self.menu(store_code, be_code) if store_code else []
        nutrition_text = self.nutrition()
        kcal_of = self.parse_nutrition(nutrition_text)

        candidates = self.pick_candidates(flat_menu) if flat_menu else []
        items = self.enrich(store_code, candidates, be_code, kcal_of) if candidates else []
        coupon_list = self.coupons(store_code, be_code) if store_code else []

        ranked = self._score(items, now, prefer)
        plans = self._build_plans(ranked, budget, people, now)

        return {
            "query": {
                "city": city, "keyword": keyword, "budget": budget,
                "people": people, "prefer": prefer,
                "beType": self.be_type,
                "beTypeName": BE_TYPE_NAMES.get(self.be_type, str(self.be_type)),
            },
            "now": now,
            "store": {key: store.get(key) for key in
                      ("storeCode", "storeName", "address", "distance",
                       "businessStatus", "businessStartTime", "businessEndTime")}
                      if store else {},
            "serving_period": serving,
            "periods": periods,
            "store_count": len(stores),
            "menu_size": len(flat_menu),
            "candidate_count": len(candidates),
            "coupon_count": len(coupon_list),
            "nutrition_rows": len(kcal_of),
            "ranked": [
                {key: item.get(key) for key in
                 ("name", "code", "category", "price", "discount", "kcal", "score", "reasons")}
                for item in ranked
            ],
            "plans": plans,
            "trace": self.trace,
            "notice": "餐品、价格、营业状态以麦当劳 MCP 实时结果与官方渠道为准；"
                      "套餐热量按默认组合单品热量求和估算；本输出仅供参考。",
        }
