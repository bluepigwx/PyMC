"""通过 MCP 服务在运行中的 PyMC 世界里建一座哥特式城堡。

前置：游戏已启动（MCP 服务在 http://127.0.0.1:8765/mcp）。
城堡建在世界原点附近，默认草地（y=0）之上，出生点就能看见。

用法:
    uv run python tool/build_gothic_castle.py
"""

import asyncio
import sys

from fastmcp import Client

MCP_URL = "http://127.0.0.1:8765/mcp"
SAVE_PATH = "save/v1/gothic_castle.json"

# 方块 id（见 mapconfig/blocks.json 或 scene_schema.md 第 4 节）
STONE = 1
COBBLE = 4
GLASS = 20
BLUE = 28      # Blue Cloth，窗玻璃顶部装饰
PURPLE = 29    # Purple Cloth，玫瑰窗中心
OBSIDIAN = 49
TORCH = 50


def region(type_, x0, x1, y0, y1, z0, z1, exclude=None, override=None):
    """构造一个 fill_regions 的 Region 参数。"""
    r = {
        "type": type_,
        "x_min": min(x0, x1), "x_max": max(x0, x1),
        "y_min": y0, "y_max": y1,
        "z_min": min(z0, z1), "z_max": max(z0, z1),
    }
    if exclude:
        r["exclude"] = [{"x": x, "y": y, "z": z} for x, y, z in exclude]
    if override:
        r["override"] = [{"x": x, "y": y, "z": z, "type": t} for x, y, z, t in override]
    return r


def build_regions():
    """哥特式城堡：主楼 + 玫瑰窗 + 尖塔 + 飞扶壁，全是一批长方体。"""
    R = []

    # 庭院石板地 + 主楼地板
    R.append(region(COBBLE, -15, 15, 1, 1, -15, 15))
    R.append(region(STONE, -9, 9, 2, 2, -9, 9))

    # ---- 四面墙 y 3..12，带竖长尖窗 ----
    lancet_x = (-7, -4, 4, 7)

    # 南墙：正门（尖拱门洞）+ 玫瑰窗 + 黑曜石门框
    ex = [(x, y, 9) for x in (-1, 0, 1) for y in (3, 4, 5)] + [(0, 6, 9)]
    ov = []
    for x in lancet_x:
        ov += [(x, y, 9, GLASS) for y in range(5, 11)]
        ov.append((x, 10, 9, BLUE))
    for dx, dy in ((0, 8), (-1, 9), (1, 9), (-2, 9), (2, 9), (0, 10)):
        ov.append((dx, dy, 9, GLASS))
    ov.append((0, 9, 9, PURPLE))
    for y in (3, 4, 5):
        ov.append((-2, y, 9, OBSIDIAN))
        ov.append((2, y, 9, OBSIDIAN))
    ov += [(-1, 6, 9, OBSIDIAN), (1, 6, 9, OBSIDIAN), (0, 7, 9, OBSIDIAN)]
    R.append(region(STONE, -9, 9, 3, 12, 9, 9, exclude=ex, override=ov))

    # 北墙：同样的尖窗 + 玫瑰窗，无门
    ov = []
    for x in lancet_x:
        ov += [(x, y, -9, GLASS) for y in range(5, 11)]
        ov.append((x, 10, -9, BLUE))
    for dx, dy in ((0, 8), (-1, 9), (1, 9), (-2, 9), (2, 9), (0, 10)):
        ov.append((dx, dy, -9, GLASS))
    ov.append((0, 9, -9, PURPLE))
    R.append(region(STONE, -9, 9, 3, 12, -9, -9, override=ov))

    # 东西墙
    for xs in (-9, 9):
        ov = []
        for z in (-7, -4, 4, 7):
            ov += [(xs, y, z, GLASS) for y in range(5, 11)]
            ov.append((xs, 10, z, BLUE))
        R.append(region(STONE, xs, xs, 3, 12, -8, 8, override=ov))

    # ---- 主楼顶部雉堞 y=13：外圈隔一格留空 ----
    ex = [(x, 13, z) for x in range(-8, 9) for z in range(-8, 9)]
    ex += [(x, 13, 9) for x in range(-9, 10) if (x + 9) % 2 == 1]
    ex += [(x, 13, -9) for x in range(-9, 10) if (x + 9) % 2 == 1]
    ex += [(9, 13, z) for z in range(-8, 9) if (z + 8) % 2 == 1]
    ex += [(-9, 13, z) for z in range(-8, 9) if (z + 8) % 2 == 1]
    R.append(region(STONE, -9, 9, 13, 13, -9, 9, exclude=ex))

    # ---- 陡坡屋顶：沿 x 的三角山花，每层 z 收 2 ----
    for i, half in enumerate((8, 6, 4, 2, 0)):
        R.append(region(COBBLE, -8, 8, 14 + i, 14 + i, -half, half))

    # ---- 四座角楼 + 雉堞 + 尖顶 ----
    for cx in (-11, 11):
        for cz in (-11, 11):
            sx = 1 if cx > 0 else -1
            sz = 1 if cz > 0 else -1
            ov = []
            for y in (9, 10):
                ov.append((cx + 2 * sx, y, cz, GLASS))
                ov.append((cx, y, cz + 2 * sz, GLASS))
            R.append(region(COBBLE, cx - 2, cx + 2, 1, 16, cz - 2, cz + 2, override=ov))

            # 塔顶雉堞
            ex = [(x, 17, z) for x in range(cx - 1, cx + 2) for z in range(cz - 1, cz + 2)]
            ex += [(x, 17, z) for x in range(cx - 2, cx + 3) for z in (cz - 2, cz + 2)
                   if (x + z) % 2 == 1]
            ex += [(x, 17, z) for x in (cx - 2, cx + 2) for z in range(cz - 1, cz + 2)
                   if (x + z) % 2 == 1]
            R.append(region(COBBLE, cx - 2, cx + 2, 17, 17, cz - 2, cz + 2, exclude=ex))

            # 尖顶：3x3 -> 十字 -> 单柱 -> 黑曜石尖
            R.append(region(COBBLE, cx - 1, cx + 1, 18, 18, cz - 1, cz + 1))
            R.append(region(COBBLE, cx - 1, cx + 1, 19, 19, cz - 1, cz + 1,
                            exclude=[(cx - 1, 19, cz - 1), (cx - 1, 19, cz + 1),
                                     (cx + 1, 19, cz - 1), (cx + 1, 19, cz + 1)]))
            R.append(region(COBBLE, cx, cx, 20, 21, cz, cz))
            R.append(region(OBSIDIAN, cx, cx, 22, 22, cz, cz))

    # ---- 飞扶壁：东西墙外侧各三根 ----
    for xs in (-1, 1):
        for z in (-6, 0, 6):
            R.append(region(STONE, 12 * xs, 12 * xs, 2, 9, z, z))    # 外柱
            R.append(region(STONE, 11 * xs, 11 * xs, 10, 10, z, z))  # 第一级拱
            R.append(region(STONE, 10 * xs, 10 * xs, 11, 11, z, z))  # 第二级拱，接墙

    # ---- 门前石路 + 火把 ----
    R.append(region(STONE, -1, 1, 1, 1, 10, 22))
    for x in (-2, 2):
        for z in (12, 18):
            R.append(region(TORCH, x, x, 2, 2, z, z))
    for x in (-14, 14):
        for z in (-14, 14):
            R.append(region(TORCH, x, x, 2, 2, z, z))

    return R


async def main():
    regions = build_regions()
    print(f"regions: {len(regions)}")

    async with Client(MCP_URL) as client:
        status = await client.call_tool("get_game_status", {})
        print(f"game: chunks={status.data['chunks_loaded']}, "
              f"camera={status.data['camera']['pos']}")

        resp = await client.call_tool("fill_regions", {"regions": regions})
        print(f"build: {resp.data}")

        save = await client.call_tool("save_scene", {"path": SAVE_PATH})
        print(f"saved: {save.data}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"failed: {e}", file=sys.stderr)
        sys.exit(1)
