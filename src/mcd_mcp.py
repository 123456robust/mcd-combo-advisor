# -*- coding: utf-8 -*-
"""麦当劳 MCP Server 的 Streamable HTTP 客户端。

仅依赖 Python 标准库，无需 pip 安装任何第三方包。

协议要点
--------
* 传输：MCP Streamable HTTP，端点 https://mcp.mcd.cn
* 鉴权：请求头 Authorization: Bearer <MCP_TOKEN>
* 会话：initialize 响应头里的 Mcp-Session-Id 需在后续请求中回传
* 限流：每个 Token 每分钟最多 600 次请求，超限返回 429

Token 只从环境变量 MCD_MCP_TOKEN 读取，绝不落盘、绝不写入仓库。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

DEFAULT_ENDPOINT = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "mcd-combo-advisor", "version": "1.0.0"}


class McpError(RuntimeError):
    """MCP 调用失败。"""


class McpClient:
    """最小可用的 MCP Streamable HTTP 客户端。"""

    def __init__(
        self,
        token: Optional[str] = None,
        endpoint: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        self.token = (token or os.environ.get("MCD_MCP_TOKEN", "")).strip()
        if not self.token:
            raise McpError(
                "缺少 MCP Token。请先设置环境变量 MCD_MCP_TOKEN：\n"
                "  Windows PowerShell: $env:MCD_MCP_TOKEN='你的Token'\n"
                "  Linux / macOS:      export MCD_MCP_TOKEN='你的Token'"
            )
        self.endpoint = endpoint or os.environ.get("MCD_MCP_URL", DEFAULT_ENDPOINT)
        self.timeout = timeout
        self.session_id: Optional[str] = None
        self.server_info: Dict[str, Any] = {}
        self._rpc_id = 0
        self._tools_cache: Optional[List[Dict[str, Any]]] = None

    # ------------------------------------------------------------------
    # 底层传输
    # ------------------------------------------------------------------
    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id

        request = urllib.request.Request(
            self.endpoint, data=body, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                ctype = response.headers.get("Content-Type", "")
                new_session = response.headers.get("Mcp-Session-Id")
                if new_session:
                    self.session_id = new_session
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code == 401:
                raise McpError("401：MCP Token 无效或未提供，请检查 MCD_MCP_TOKEN") from exc
            if exc.code == 429:
                raise McpError("429：触发限流（600 次/分钟），请降低调用频率") from exc
            raise McpError(f"HTTP {exc.code}: {detail[:300]}") from exc
        except urllib.error.URLError as exc:
            raise McpError(f"网络请求失败：{exc.reason}") from exc

        return self._decode(raw, ctype)

    @staticmethod
    def _decode(raw: str, ctype: str) -> Dict[str, Any]:
        """兼容 JSON 与 SSE 两种响应体。"""
        if "text/event-stream" in ctype:
            objects: List[Dict[str, Any]] = []
            for line in raw.splitlines():
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if not chunk:
                    continue
                try:
                    objects.append(json.loads(chunk))
                except json.JSONDecodeError:
                    continue
            for obj in objects:
                if "result" in obj or "error" in obj:
                    return obj
            return objects[0] if objects else {}
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _rpc(
        self, method: str, params: Optional[Dict[str, Any]] = None, notify: bool = False
    ) -> Dict[str, Any]:
        self._rpc_id += 1
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if not notify:
            payload["id"] = self._rpc_id
        if params is not None:
            payload["params"] = params

        response = self._post(payload)
        if notify:
            return {}
        if "error" in response:
            err = response["error"]
            raise McpError(f"{method} 失败 [{err.get('code')}]: {err.get('message')}")
        return response.get("result", {})

    # ------------------------------------------------------------------
    # MCP 生命周期
    # ------------------------------------------------------------------
    def initialize(self) -> Dict[str, Any]:
        result = self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
        )
        self.server_info = result.get("serverInfo", {})
        self._rpc("notifications/initialized", notify=True)
        return result

    def list_tools(self, refresh: bool = False) -> List[Dict[str, Any]]:
        if self._tools_cache is not None and not refresh:
            return self._tools_cache
        result = self._rpc("tools/list")
        self._tools_cache = result.get("tools", [])
        return self._tools_cache

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        return self._unwrap(result)

    @staticmethod
    def _unwrap(result: Dict[str, Any]) -> Any:
        """把 MCP content 数组还原成 Python 对象。"""
        if "structuredContent" in result and result["structuredContent"]:
            return result["structuredContent"]

        texts: List[str] = []
        for item in result.get("content", []):
            if item.get("type") == "json":
                return item.get("json")
            if item.get("type") == "text":
                texts.append(item.get("text", ""))

        joined = "\n".join(texts).strip()
        if not joined:
            return result
        try:
            return json.loads(joined)
        except json.JSONDecodeError:
            return joined

    # ------------------------------------------------------------------
    def __enter__(self) -> "McpClient":
        self.initialize()
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def close(self) -> None:
        if not self.session_id:
            return
        request = urllib.request.Request(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Mcp-Session-Id": self.session_id,
            },
            method="DELETE",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
        except Exception:  # noqa: BLE001 - 关闭失败无需中断流程
            pass
        self.session_id = None


def connect(token: Optional[str] = None, endpoint: Optional[str] = None) -> McpClient:
    """建立并完成握手的连接。"""
    client = McpClient(token=token, endpoint=endpoint)
    client.initialize()
    return client
