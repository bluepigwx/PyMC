"""临时 Agent 服务端：等 PyMC 客户端连上来，下发建造指令。

用法：
    uv run python scene_server.py
然后启动 main.py（客户端会连 localhost:8001）。
"""
import socket
import struct
import json
import time

HOST = "0.0.0.0"
PORT = 8001
HEADER = ">I"


def send_frame(sock, obj):
    payload = json.dumps(obj).encode("utf-8")
    sock.sendall(struct.pack(HEADER, len(payload)) + payload)


def recv_exactly(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("client disconnected")
        buf.extend(chunk)
    return bytes(buf)


def recv_frame(sock):
    (length,) = struct.unpack(HEADER, recv_exactly(sock, 4))
    return json.loads(recv_exactly(sock, length).decode("utf-8"))


def pyramid_regions(cx=0, cz=0, base_y=1, half=6, block=12):
    """金字塔：每层向内收 1 格，共 half+1 层。"""
    regions = []
    for i in range(half + 1):
        r = half - i
        y = base_y + i
        regions.append({
            "type": block,
            "x": [cx - r, cx + r],
            "y": [y, y],
            "z": [cz - r, cz + r],
        })
    return regions


# 坦克大战第一关：13x13 tile
# B=砖墙 S=钢墙 E=基地(老鹰) .=空地
BATTLE_CITY_STAGE1 = [
    ".............",
    "..BB..B..BB..",
    "..BB..B..BB..",
    "..BB..B..BB..",
    "..BB..B..BB..",
    ".............",
    "BB.BB.S.BB.BB",
    ".............",
    "..BB..B..BB..",
    "..BB..B..BB..",
    "..BB..B..BB..",
    "..BB.BBB.BB..",
    ".....B.B.....",
]

TILE_BLOCK = {
    "B": 45,   # Bricks
    "S": 42,   # Iron Block
    "E": 41,   # Gold Block -- 基地
}

EAGLE_TILE = (6, 12)  # (col, row)


def battle_city_regions(y_low=1, y_high=2, tile=2):
    """把 tile 网格展开为区域列表，地图以世界原点为中心。"""
    rows = len(BATTLE_CITY_STAGE1)
    cols = len(BATTLE_CITY_STAGE1[0])
    x0 = -(cols * tile) // 2
    z0 = -(rows * tile) // 2

    regions = []
    for r, line in enumerate(BATTLE_CITY_STAGE1):
        for c, ch in enumerate(line):
            if ch == ".":
                continue
            block = TILE_BLOCK[ch]
            x = x0 + c * tile
            z = z0 + r * tile
            regions.append({
                "type": block,
                "x": [x, x + tile - 1],
                "y": [y_low, y_high],
                "z": [z, z + tile - 1],
            })

    # 基地
    ec, er = EAGLE_TILE
    ex = x0 + ec * tile
    ez = z0 + er * tile
    regions.append({
        "type": TILE_BLOCK["E"],
        "x": [ex, ex + tile - 1],
        "y": [y_low, y_high],
        "z": [ez, ez + tile - 1],
    })
    return regions


def clear_region(y_low=1, y_high=14, half=16):
    return [{
        "type": 0,
        "x": [-half, half - 1],
        "y": [y_low, y_high],
        "z": [-half, half - 1],
    }]


def house_regions():
    """9x9 小房子：木地板 + 砖墙 + 玻璃窗 + 门洞 + 阶梯屋顶。"""
    regions = []

    # 地面草地
    regions.append({"type": 2, "x": [-9, 9], "y": [0, 0], "z": [-9, 9]})
    # 木地板
    regions.append({"type": 5, "x": [-4, 4], "y": [1, 1], "z": [-4, 4]})

    # 四面墙 y=2..5，砖墙；南墙留门洞(x=0,y=2..3)
    regions.append({
        "type": 45, "x": [-4, 4], "y": [2, 5], "z": [4, 4],
        "exclude": [{"x": 0, "y": 2, "z": 4}, {"x": 0, "y": 3, "z": 4}],
        "override": [
            {"x": -2, "y": 4, "z": 4, "type": 20},
            {"x": 2, "y": 4, "z": 4, "type": 20},
        ],
    })
    regions.append({
        "type": 45, "x": [-4, 4], "y": [2, 5], "z": [-4, -4],
        "override": [
            {"x": -2, "y": 4, "z": -4, "type": 20},
            {"x": 0, "y": 4, "z": -4, "type": 20},
            {"x": 2, "y": 4, "z": -4, "type": 20},
        ],
    })
    regions.append({
        "type": 45, "x": [-4, -4], "y": [2, 5], "z": [-3, 3],
        "override": [
            {"x": -4, "y": 4, "z": -1, "type": 20},
            {"x": -4, "y": 4, "z": 1, "type": 20},
        ],
    })
    regions.append({
        "type": 45, "x": [4, 4], "y": [2, 5], "z": [-3, 3],
        "override": [
            {"x": 4, "y": 4, "z": -1, "type": 20},
            {"x": 4, "y": 4, "z": 1, "type": 20},
        ],
    })

    # 四角木柱
    for cx in (-4, 4):
        for cz in (-4, 4):
            regions.append({"type": 17, "x": [cx, cx], "y": [2, 5], "z": [cz, cz]})

    # 屋顶：y=6 出檐铺满封顶，往上每层收 2 格
    regions.append({"type": 4, "x": [-5, 5], "y": [6, 6], "z": [-5, 5]})
    regions.append({"type": 4, "x": [-3, 3], "y": [7, 7], "z": [-3, 3]})
    regions.append({"type": 4, "x": [-1, 1], "y": [8, 8], "z": [-1, 1]})

    # 门前石板路
    regions.append({"type": 1, "x": [-1, 1], "y": [1, 1], "z": [5, 8]})
    # 门口两侧火把
    regions.append({"type": 50, "x": [-1, -1], "y": [3, 3], "z": [5, 5]})
    regions.append({"type": 50, "x": [1, 1], "y": [3, 3], "z": [5, 5]})

    return regions


# 方块常量
WHITE = 80   # Snow Block
GLASS = 20
STONE = 1
COBBLE = 4
PLANK = 5
LOG = 17
BRICK = 45
GOLD = 41
WATER = 9
FLOWER = 37
ORANGE = 22   # Orange Cloth


def modern_villa_regions():
    """现代风格别墅：白色雪块墙体 + 玻璃幕墙 + 平顶 + 泳池庭院。"""
    regions = []

    # 场地
    regions.append({"type": 2, "x": [-13, 13], "y": [0, 0], "z": [-9, 13]})
    regions.append({"type": STONE, "x": [-5, 5], "y": [1, 1], "z": [-5, 5]})
    regions.append({"type": WHITE, "x": [-4, 4], "y": [2, 2], "z": [-4, 4]})

    # 一层墙体 y=3..4，南面中央留门洞，四面大玻璃
    regions.append({
        "type": WHITE, "x": [-4, 4], "y": [3, 4], "z": [4, 4],
        "exclude": [{"x": -1, "y": 3, "z": 4}, {"x": 0, "y": 3, "z": 4}, {"x": 1, "y": 3, "z": 4}],
        "override": [
            {"x": -3, "y": 3, "z": 4, "type": GLASS}, {"x": -3, "y": 4, "z": 4, "type": GLASS},
            {"x": 3, "y": 3, "z": 4, "type": GLASS}, {"x": 3, "y": 4, "z": 4, "type": GLASS},
        ],
    })
    regions.append({
        "type": WHITE, "x": [-4, 4], "y": [3, 4], "z": [-4, -4],
        "override": [
            {"x": x, "y": y, "z": -4, "type": GLASS}
            for x in (-3, -1, 1, 3) for y in (3, 4)
        ],
    })
    for c in (-4, 4):
        regions.append({
            "type": WHITE, "x": [c, c], "y": [3, 4], "z": [-3, 3],
            "override": [
                {"x": c, "y": y, "z": z, "type": GLASS}
                for z in (-2, 0, 2) for y in (3, 4)
            ],
        })

    # 二层楼板（比一层外扩 1 格出檐）+ 二层玻璃幕墙
    regions.append({"type": WHITE, "x": [-5, 5], "y": [5, 5], "z": [-5, 5]})
    regions.append({
        "type": WHITE, "x": [-3, 3], "y": [6, 7], "z": [3, 3],
        "override": [
            {"x": x, "y": y, "z": 3, "type": GLASS}
            for x in (-2, -1, 0, 1, 2) for y in (6, 7)
        ],
    })
    regions.append({
        "type": WHITE, "x": [-3, 3], "y": [6, 7], "z": [-3, -3],
        "override": [
            {"x": x, "y": y, "z": -3, "type": GLASS}
            for x in (-2, -1, 0, 1, 2) for y in (6, 7)
        ],
    })
    for c in (-3, 3):
        regions.append({
            "type": WHITE, "x": [c, c], "y": [6, 7], "z": [-2, 2],
            "override": [
                {"x": c, "y": y, "z": z, "type": GLASS}
                for z in (-1, 0, 1) for y in (6, 7)
            ],
        })

    # 平顶屋面 y=8（白色 + 橙色装饰带）+ 女儿墙 y=9
    regions.append({"type": WHITE, "x": [-5, 5], "y": [8, 8], "z": [-5, 5]})
    regions.append({
        "type": WHITE, "x": [-5, 5], "y": [9, 9], "z": [-5, 5],
        "exclude": [{"x": x, "y": 9, "z": z}
                    for x in range(-4, 5) for z in range(-4, 5)],
    })
    stripe = []
    for k in range(0, 7, 2):
        stripe.append({"x": k - 3, "y": 9, "z": -4, "type": ORANGE})
        stripe.append({"x": k - 3, "y": 9, "z": 4, "type": ORANGE})
    for k in range(0, 5, 2):
        stripe.append({"x": -4, "y": 9, "z": k - 2, "type": ORANGE})
        stripe.append({"x": 4, "y": 9, "z": k - 2, "type": ORANGE})
    regions.append({"type": WHITE, "x": [-4, 4], "y": [9, 9], "z": [-4, 4], "override": stripe})

    # 一层内饰：地面交替白/橙色，隔断墙
    regions.append({
        "type": WHITE, "x": [-3, 3], "y": [3, 3], "z": [-3, 3],
        "override": [{"x": x, "y": 3, "z": z, "type": ORANGE}
                     for x in range(-3, 4, 2) for z in range(-3, 4, 2)],
    })
    regions.append({"type": ORANGE, "x": [2, 2], "y": [3, 3], "z": [-1, 1]})

    # 庭院：泳池（石框 + 水）+ 石板路 + 花
    regions.append({"type": STONE, "x": [-9, -4], "y": [1, 1], "z": [6, 11]})
    regions.append({"type": WATER, "x": [-8, -5], "y": [2, 2], "z": [7, 10]})
    regions.append({"type": STONE, "x": [-1, 1], "y": [1, 1], "z": [6, 12]})
    regions.append({"type": FLOWER, "x": [5, 8], "y": [1, 1], "z": [7, 7]})
    regions.append({"type": FLOWER, "x": [5, 7], "y": [1, 1], "z": [10, 10]})
    for cx, cz in ((-6, -6), (6, -6), (-6, 6), (6, 6)):
        regions.append({"type": 50, "x": [cx, cx], "y": [1, 1], "z": [cz, cz]})

    return regions


BRICK = 45
GRASS = 2
STONE = 1


def _ring_gaps(lo, hi, y):
    """城墙垛口的空缺格：外圈每隔 1 格留空。"""
    gaps = []
    for x in range(lo, hi + 1):
        if (x - lo) % 2 == 0:
            gaps.append({"x": x, "y": y, "z": lo})
            gaps.append({"x": x, "y": y, "z": hi})
    for z in range(lo + 1, hi):
        if (z - lo) % 2 == 1:
            gaps.append({"x": lo, "y": y, "z": z})
            gaps.append({"x": hi, "y": y, "z": z})
    return gaps


def brick_castle_regions():
    """砖石城堡：只用 Stone / Grass / Bricks。"""
    regions = []

    # 地面 + 石砌庭院
    regions.append({"type": GRASS, "x": [-14, 14], "y": [0, 0], "z": [-14, 14]})
    regions.append({"type": STONE, "x": [-6, 6], "y": [1, 1], "z": [-6, 6]})

    # 外墙 y=2..6
    regions.append({
        "type": BRICK, "x": [-6, 6], "y": [2, 6], "z": [6, 6],
        "exclude": [{"x": x, "y": y, "z": 6} for x in (-1, 0, 1) for y in (2, 3, 4)],
        "override": [{"x": x, "y": 4, "z": 6, "type": STONE} for x in (-4, 4)],
    })
    regions.append({
        "type": BRICK, "x": [-6, 6], "y": [2, 6], "z": [-6, -6],
        "override": [{"x": x, "y": 4, "z": -6, "type": STONE} for x in (-4, -1, 0, 1, 4)],
    })
    for c in (-6, 6):
        regions.append({
            "type": BRICK, "x": [c, c], "y": [2, 6], "z": [-5, 5],
            "override": [{"x": c, "y": 4, "z": z, "type": STONE} for z in (-3, 0, 3)],
        })

    # 城墙顶雉堞 y=7
    regions.append({
        "type": BRICK, "x": [-6, 6], "y": [7, 7], "z": [-6, 6],
        "exclude": _ring_gaps(-6, 6, 7),
    })

    # 四座角楼 x=±7、z=±7，5x5，高到 y=8，顶部垛口
    for cx in (-7, 7):
        for cz in (-7, 7):
            regions.append({"type": BRICK, "x": [cx - 1, cx + 1], "y": [2, 8], "z": [cz - 1, cz + 1]})
            regions.append({
                "type": BRICK, "x": [cx - 2, cx + 2], "y": [9, 9], "z": [cz - 2, cz + 2],
                "exclude": _ring_gaps(cx - 2, cx + 2, 9) ,
            })
            # 角楼内的石地面
            regions.append({"type": STONE, "x": [cx - 1, cx + 1], "y": [1, 1], "z": [cz - 1, cz + 1]})

    # 内城主楼 x/z = -3..3，y=2..6，顶部用 Grass 铺面
    regions.append({
        "type": BRICK, "x": [-3, 3], "y": [2, 6], "z": [3, 3],
        "exclude": [{"x": x, "y": y, "z": 3} for x in (-1, 0, 1) for y in (2, 3, 4)],
        "override": [{"x": x, "y": 5, "z": 3, "type": STONE} for x in (-2, 0, 2)],
    })
    regions.append({
        "type": BRICK, "x": [-3, 3], "y": [2, 6], "z": [-3, -3],
        "override": [{"x": x, "y": 5, "z": -3, "type": STONE} for x in (-2, 0, 2)],
    })
    for c in (-3, 3):
        regions.append({
            "type": BRICK, "x": [c, c], "y": [2, 6], "z": [-2, 2],
            "override": [{"x": c, "y": 5, "z": z, "type": STONE} for z in (-1, 1)],
        })
    # 主楼石质楼板 + 草皮屋顶 + 砖砌女儿墙
    regions.append({"type": STONE, "x": [-3, 3], "y": [7, 7], "z": [-3, 3]})
    regions.append({"type": GRASS, "x": [-3, 3], "y": [8, 8], "z": [-3, 3]})
    regions.append({
        "type": BRICK, "x": [-3, 3], "y": [9, 9], "z": [-3, 3],
        "exclude": [{"x": x, "y": 9, "z": z} for x in range(-2, 3) for z in range(-2, 3)],
        "override": [{"x": x, "y": 9, "z": 3, "type": STONE} for x in (-3, 0, 3)],
    })

    # 庭院：石路 + 草块点缀
    regions.append({"type": STONE, "x": [-1, 1], "y": [1, 1], "z": [7, 14]})
    regions.append({"type": GRASS, "x": [3, 5], "y": [1, 1], "z": [3, 5]})
    regions.append({"type": GRASS, "x": [-5, -3], "y": [1, 1], "z": [3, 5]})
    return regions


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(1)
    print(f"listening on {HOST}:{PORT}, waiting for PyMC client...", flush=True)

    conn, addr = srv.accept()
    print(f"client connected: {addr}", flush=True)

    send_frame(conn, {"cmd": "connected", "params": {"session_id": "local-builder"}})

    conn.settimeout(180)

    tasks = [
        ("clear", "set_blocks_region", {"regions": clear_region()}),
        ("brick-castle", "set_blocks_region", {"regions": brick_castle_regions()}),
        ("save", "save_scene_json", {"path": "scene.json"}),
        ("clear-again", "set_blocks_region", {"regions": clear_region()}),
        ("load", "load_scene_json", {"path": "scene.json", "clear": True}),
    ]

    for name, cmd, params in tasks:
        send_frame(conn, {"cmd": cmd, "request_id": name, "params": params})
        print(f"[{name}] sent {cmd}", flush=True)
        try:
            resp = recv_frame(conn)
            print(f"[{name}] response: {resp}", flush=True)
        except Exception as e:
            print(f"[{name}] recv failed: {e}", flush=True)
            break

    # 保持连接，方便后续继续下发指令
    conn.settimeout(None)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        conn.close()
        srv.close()


if __name__ == "__main__":
    main()
