"""GNS3 MCP 测试通用客户端。

封装：.env 加载 → SSE 连接 → 调用工具 → 美化输出。
所有 mcp-manual-test/<tool>/test_*.py 共用本模块，避免重复样板。

用法（在某个工具的测试脚本里）:

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 把 mcp-manual-test/ 加入 sys.path
    from _lib.gns3_mcp import connect, call_tool, format_result, list_tools

    async def main():
        async with connect() as session:           # 连接 + initialize
            result, elapsed = await call_tool(session, "appliance_get", {"appliance_id": "..."})
        print(format_result(result))
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession
from mcp.client.sse import sse_client


def _load_env() -> None:
    """从本文件位置向上查找项目根的 .env 并加载（不依赖 python-dotenv）。

    已存在的环境变量优先于 .env 中的值。
    """
    here = Path(__file__).resolve()
    for d in [here.parent, *here.parents]:
        env_file = d / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())
            return
    # 没找到 .env 也没关系，环境变量里可能已有配置


def config() -> tuple[str, str]:
    """返回 (GNS3_MCP_URL, GNS3_MCP_TOKEN)，缺失则直接报错退出。"""
    _load_env()
    url = os.environ.get("GNS3_MCP_URL")
    token = os.environ.get("GNS3_MCP_TOKEN")
    if not url or not token:
        raise SystemExit(
            "缺少 GNS3_MCP_URL / GNS3_MCP_TOKEN，请在项目根目录的 .env 中配置（参见 .env.example）"
        )
    return url, token


def headers() -> dict[str, str]:
    """构造 MCP 请求头（Bearer token 鉴权）。"""
    _, token = config()
    return {"Authorization": f"Bearer {token}"}


@asynccontextmanager
async def connect():
    """连接 GNS3 MCP（SSE transport），yield 一个已完成 initialize 的 ClientSession。

    用法::

        async with connect() as session:
            ...  # 在同一个会话里可多次调用工具
    """
    url, _ = config()
    # sse_client 会: 1) 建立 SSE GET 长连接; 2) 收到 endpoint 后向其 POST JSON-RPC。
    async with sse_client(url, headers=headers()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def list_tools(session: ClientSession):
    """返回服务器暴露的全部工具对象。"""
    return (await session.list_tools()).tools


def find_tool(tools, name: str):
    """在工具列表里按名称查找，返回工具对象或 None。"""
    return next((t for t in tools if t.name == name), None)


async def call_tool(session: ClientSession, name: str, arguments: dict | None = None):
    """调用一个工具，返回 (CallToolResult, 耗时秒数)。"""
    t0 = time.perf_counter()
    result = await session.call_tool(name, arguments or {})
    return result, time.perf_counter() - t0


def _unwrap_envelope(obj):
    """递归解开 {"type":"text","text": <str|obj>} 形式的嵌套包裹。

    GNS3 MCP 的部分工具会把结果再套一层 text content envelope，
    例如 appliance_list 的 text 实为 '{"type":"text","text":"{...}"}'。
    返回最内层对象；若内层是普通文本字符串则返回该字符串。
    """
    for _ in range(8):
        if isinstance(obj, dict) and set(obj.keys()) <= {"type", "text"} and "text" in obj:
            inner = obj["text"]
            if isinstance(inner, str):
                try:
                    inner = json.loads(inner)
                except ValueError:
                    return inner  # 内层是普通文本，停止解包
            obj = inner
            continue
        break
    return obj


def _pretty_json_text(text: str) -> str:
    """若文本是 JSON（含嵌套 envelope），解开并美化；否则原样返回。"""
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return text
    obj = _unwrap_envelope(obj)
    if isinstance(obj, str):
        return obj
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except (ValueError, TypeError):
        return text


def format_result(result) -> str:
    """把 CallToolResult 的 ``content`` 块渲染成可读字符串（仅限 MCP 标准 wire 层）。"""
    lines: list[str] = []
    lines.append(f"isError: {bool(getattr(result, 'isError', False))}")

    content = getattr(result, "content", []) or []
    for i, block in enumerate(content):
        btype = getattr(block, "type", "?")
        if btype == "text":
            lines.append(f"[content {i}] text:\n{_pretty_json_text(block.text)}")
        else:
            lines.append(f"[content {i}] {btype}: {block}")
    return "\n".join(lines)


def raw_result(result) -> dict:
    """取 MCP 原始返回（wire 层数据），移除 SDK 私有字段。

    并将 ``content[].text`` 中 GNS3 服务器多余包裹的
    ``{"type":"text","text":"真实数据"}`` 层递归解开。
    """
    raw = json.loads(result.model_dump_json())
    raw.pop("structuredContent", None)
    raw.pop("structured_content", None)
    for block in raw.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            try:
                parsed = json.loads(block["text"])
                # 内层 text 也是 JSON 字符串，同样展开
                if isinstance(parsed, dict) and "text" in parsed and isinstance(parsed["text"], str):
                    try:
                        parsed["text"] = json.loads(parsed["text"])
                    except (ValueError, TypeError):
                        pass
                block["text"] = parsed
            except (ValueError, TypeError):
                pass
    return raw


def payload(result):
    """从 MCP 返回的 ``content[0].text`` 里取出真实数据对象，返回 ``(data, source)``。

    只走标准 MCP 的 ``content`` 数组（与 Claude Code 行为一致），
    不做 SDK 私有的 ``structuredContent`` 提取。
    遇到后端双重 envelope 时自动解开。
    """
    for block in getattr(result, "content", []) or []:
        if getattr(block, "type", "") == "text":
            try:
                obj = _unwrap_envelope(json.loads(block.text))
            except ValueError:
                continue
            if isinstance(obj, (dict, list)):
                return obj, "content[].text"
    return None, None


def save_record(
    script_file: str | Path,
    *,
    tool: str,
    arguments: dict | None,
    result,
    elapsed: float,
    input_schema: dict | None = None,
) -> Path:
    """把本次调用记录写到「脚本同目录」下的一个 JSON 文件，返回文件路径。

    记录包含三部分：
      - 调用数据：工具名、入参、入参 schema、调用时间、耗时；
      - MCP 原始返回：未解包的 wire 层结果（raw_result）；
      - 格式化内容：解开 envelope 后的人类可读文本（formatted）。
    文件名形如 ``<tool>__YYYYmmdd_HHMMSS.json``，每次运行新增一个（保留历史）。
    """
    out_dir = Path(script_file).resolve().parent
    now = datetime.datetime.now()
    path = out_dir / f"{tool}__{now.strftime('%Y%m%d_%H%M%S')}.json"
    record = {
        "tool": tool,
        "called_at": now.isoformat(timespec="seconds"),
        "elapsed_ms": round(elapsed * 1000, 1),
        "call": {
            "arguments": arguments or {},
            "input_schema": input_schema,
        },
        "result": {
            "is_error": bool(getattr(result, "isError", False)),
            "raw": raw_result(result),  # MCP 原始返回（wire 层数据，不含 SDK 私有字段）
        },
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


async def call_and_record(
    session: ClientSession,
    *,
    script_file: str | Path,
    tool: str,
    arguments: dict | None = None,
    input_schema: dict | None = None,
    save: bool = True,
):
    """调用工具并（默认）把调用数据 + 原始返回落盘到脚本同目录。

    返回 ``(result, elapsed, saved_path_or_None)``。
    """
    result, elapsed = await call_tool(session, tool, arguments)
    saved = None
    if save:
        saved = save_record(
            script_file, tool=tool, arguments=arguments, result=result,
            elapsed=elapsed, input_schema=input_schema,
        )
        print(f"💾 已保存记录: {saved}")
    return result, elapsed, saved


def run(coro):
    """运行 async 协程的快捷入口（统一事件循环处理）。"""
    return asyncio.run(coro)
