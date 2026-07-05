"""最小 MCP stdio 服务器（JSON-RPC 2.0 over 换行分隔）。

只覆盖本项目 pack 需要的方法：initialize / initialized / tools/list / tools/call。
不引入官方 mcp SDK，避免多一个 pip 依赖；协议版本 pin 到 2024-11-05（客户端
若报更新版本也回退到 2024-11-05，服务器只声明 tools 能力）。

约定：
  - 工具处理函数返回值：
      str            -> 一段文本
      list           -> 已经是 MCP content 列表
      其它           -> 一段 JSON 文本（indent=2，ensure_ascii=False）
  - 抛异常 -> JSON-RPC error（code=-32000，message=str(e)）
  - stdout 只准写 JSON-RPC；一切诊断信息只准 stderr（Science 那侧不会读 stderr）。
"""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Callable, Dict, List


class MCPServer:
    def __init__(self, name: str, version: str = "0.1.0"):
        self.name = name
        self.version = version
        self.tools: Dict[str, Dict[str, Any]] = {}

    def tool(self, name: str, description: str, input_schema: Dict[str, Any]):
        """@server.tool(name, description, input_schema) 装饰器。"""
        def deco(fn: Callable[..., Any]):
            self.tools[name] = {
                "description": description,
                "inputSchema": input_schema,
                "handler": fn,
            }
            return fn
        return deco

    # ---------- 协议实现 ----------
    def _handle(self, req: Dict[str, Any]):
        method = req.get("method")
        params = req.get("params") or {}

        if method == "initialize":
            # 客户端会传自己声明的 protocolVersion；我们回同名值，只声明 tools 能力。
            return {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": self.name, "version": self.version},
            }
        if method in ("initialized", "notifications/initialized"):
            return None  # 通知，不回

        if method == "tools/list":
            return {
                "tools": [
                    {
                        "name": n,
                        "description": t["description"],
                        "inputSchema": t["inputSchema"],
                    }
                    for n, t in self.tools.items()
                ]
            }

        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments", {}) or {}
            if name not in self.tools:
                raise ValueError(f"unknown tool: {name}")
            result = self.tools[name]["handler"](**args)
            if isinstance(result, str):
                content: List[Dict[str, Any]] = [{"type": "text", "text": result}]
            elif isinstance(result, list):
                content = result
            else:
                content = [{
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, indent=2, default=str),
                }]
            return {"content": content, "isError": False}

        raise ValueError(f"unknown method: {method}")

    def run(self) -> None:
        """阻塞读 stdin，按行处理 JSON-RPC。stdin 关闭 = 正常退出。"""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError as e:
                sys.stderr.write(f"[mcp] bad json: {e}\n")
                continue
            req_id = req.get("id")
            is_notification = "id" not in req
            try:
                result = self._handle(req)
                if not is_notification and result is not None:
                    self._send({"jsonrpc": "2.0", "id": req_id, "result": result})
            except Exception as e:  # noqa: BLE001
                sys.stderr.write(f"[mcp] handler error: {e}\n{traceback.format_exc()}")
                if not is_notification:
                    self._send({
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32000, "message": str(e)},
                    })

    def _send(self, obj: Dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()
