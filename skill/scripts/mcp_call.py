"""命令行调用 PyMC MCP 工具（独立版，只依赖 fastmcp）。

前置：PyMC 游戏已启动（MCP 服务在 http://127.0.0.1:8765/mcp）。

用法:
    python mcp_call.py <tool_name> [json_args]
    python mcp_call.py <tool_name> --args-file params.json

例:
    python mcp_call.py get_game_status
    python mcp_call.py reset_scene '{"path": "scene.json"}'
    python mcp_call.py fill_regions --args-file regions.json
"""

import asyncio
import json
import sys

from fastmcp import Client

MCP_URL = "http://127.0.0.1:8765/mcp"


async def main():
    name = sys.argv[1]
    args = {}
    if len(sys.argv) > 2:
        if sys.argv[2] == "--args-file":
            with open(sys.argv[3], "r", encoding="utf-8") as f:
                args = json.load(f)
        else:
            args = json.loads(sys.argv[2])

    async with Client(MCP_URL) as client:
        r = await client.call_tool(name, args)
        print(json.dumps(r.data, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    asyncio.run(main())
