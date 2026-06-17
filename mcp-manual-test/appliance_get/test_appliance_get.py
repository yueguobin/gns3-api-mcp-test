#!/usr/bin/env python3
"""测试 MCP 工具 appliance_get。

通过 MCP（SSE）连接 GNS3 服务器，调用 appliance_get 获取单个 appliance 的详细信息。
appliance_get 需要 appliance_id（UUID），本脚本支持两种取值方式：
  1) --appliance-id <UUID>  直接指定；
  2) 不指定时，自动调用 appliance_list 取第一个 appliance 的 id。

运行:
    # 自动取 id
    ../../.venv/bin/python test_appliance_get.py
    # 手动指定 id
    ../../.venv/bin/python test_appliance_get.py --appliance-id <UUID>
    # 只看 appliance_get 的入参 schema
    ../../.venv/bin/python test_appliance_get.py --show-schema
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# 把 mcp-manual-test/ 加入 sys.path，以便导入共用库 _lib
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib.gns3_mcp import (  # noqa: E402
    call_and_record,
    call_tool,
    connect,
    find_tool,
    format_result,
    list_tools,
    payload,
)

TOOL = "appliance_get"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="测试 MCP 工具 appliance_get")
    p.add_argument(
        "--appliance-id",
        help="直接指定 appliance 的 UUID；不填则自动从 appliance_list 取第一个",
    )
    p.add_argument(
        "--show-schema",
        action="store_true",
        help="打印 appliance_get 的入参 schema 后退出",
    )
    p.add_argument(
        "--no-save",
        action="store_true",
        help="不把调用数据 / MCP 原始返回落盘到脚本同目录",
    )
    return p.parse_args()


def extract_ids(list_result) -> list[tuple[str, str]]:
    """从 appliance_list 的 MCP 返回对象里提取 (appliance_id, name) 列表。

    走标准 ``content[0].text`` → ``json.loads`` 路径（与 Claude Code 一致）。
    """
    data, _ = payload(list_result)
    items = data if isinstance(data, list) else (data or {}).get("appliances", [])
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        aid = it.get("appliance_id") or it.get("id")
        if aid:
            out.append((str(aid), it.get("name", "")))
    # 去重保序
    seen: set[str] = set()
    uniq = []
    for aid, name in out:
        if aid not in seen:
            seen.add(aid)
            uniq.append((aid, name))
    return uniq


async def main() -> None:
    args = parse_args()

    async with connect() as session:
        # 1) 确认目标工具存在
        tools = await list_tools(session)
        tool = find_tool(tools, TOOL)
        if not tool:
            print(f"⚠️  服务器未暴露工具 {TOOL}")
            return
        print(f"✓ 已连接 GNS3 MCP，工具 {TOOL} 存在")

        if args.show_schema:
            print(json.dumps(tool.inputSchema, ensure_ascii=False, indent=2))
            return

        # 2) 确定 appliance_id
        appliance_id = args.appliance_id
        if not appliance_id:
            print("\n未指定 --appliance-id，调用 appliance_list 自动获取 ...")
            lr, _ = await call_tool(session, "appliance_list", {})
            ids = extract_ids(lr)
            if not ids:
                print("⚠️  appliance_list 未解析出 id，请用 --appliance-id <UUID> 手动指定。")
                print("原始 content[0].text（前 200 字符）:")
                print(repr(getattr(lr.content[0], "text", ""))[:200])
                return
            appliance_id, name = ids[0]
            print(f"  共 {len(ids)} 个 appliance，取第一个: {name or '(无名)'} -> {appliance_id}")

        # 3) 调用 appliance_get（并把调用数据 + MCP 原始返回落盘到脚本同目录）
        print(f"\n=== 调用 {TOOL}({{'appliance_id': '{appliance_id}'}}) ===")
        result, elapsed, _ = await call_and_record(
            session,
            script_file=__file__,
            tool=TOOL,
            arguments={"appliance_id": appliance_id},
            input_schema=tool.inputSchema,
            save=not args.no_save,
        )

    # 4) 输出结果 + 耗时
    print(format_result(result))

    # 与 Claude Code 一致的取值方式：content[0].text → json.loads 一次
    data, src = payload(result)
    if isinstance(data, dict):
        print(f"\n✓ 用 {src} 取值，json.loads 一次即得 {len(data)} 个字段：")
        print(f"  name        : {data.get('name')}")
        print(f"  category    : {data.get('category')}")
        qemu = data.get("qemu") or {}
        print(f"  qemu.ram    : {qemu.get('ram')}")
        print(f"  images      : {len(data.get('images', []))} 个")

    print(f"\n⏱  {TOOL} 耗时 {elapsed * 1000:.1f} ms")
    sys.exit(1 if getattr(result, "isError", False) else 0)


if __name__ == "__main__":
    asyncio.run(main())
