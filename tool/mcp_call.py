"""命令行调用 PyMC MCP 工具。

前置：游戏已启动（MCP 服务在 http://127.0.0.1:8765/mcp）。

用法:
    uv run python tool/mcp_call.py <tool_name> [json_args]

例:
    uv run python tool/mcp_call.py get_game_status
    uv run python tool/mcp_call.py load_scene '{"path": "save/v1/pagoda.json", "clear": true}'
"""

import asyncio
import json
import sys

from fastmcp import Client

MCP_URL = "http://127.0.0.1:8765/mcp"


async def main():
    name = sys.argv[1]
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    async with Client(MCP_URL) as client:
        r = await client.call_tool(name, args)
        print(json.dumps(r.data, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    asyncio.run(main())
