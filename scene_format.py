"""PyMC 场景格式 v1 的编解码器。

格式定义见 mapv1.md。核心是把世界切成 16×16×16 的 section，
每段用「局部调色板 + 游程编码」写成 JSON。

术语：
    section  16×16×16 = 4096 格的小立方体
    palette  该 section 内出现的方块 id 列表，后面用它的下标代替 id
    RLE      游程编码，[次数, 下标, 次数, 下标, ...]
    YZX      展开顺序，先变 x，x 走完换 z，z 走完换 y

方块类型说明（名字、贴图、模型）不写进场景文件，统一放在
mapconfig/blocks.json 里，由 gen_block_defs.py 从 mapconfig/blocks.mcpy 生成。
场景文件只存方块 id，用 block_defs 字段指向那份共享定义。

本模块不依赖 OpenGL，可脱离游戏进程单独使用。
"""

from __future__ import annotations

import json
import math
import os
import time
from collections import OrderedDict

FORMAT_NAME = "pymc_scene"
FORMAT_VERSION = 1
SECTION_SIZE = 16
ORDER = "yzx"

# 共享的方块类型定义文件，场景文件里只记这个相对路径
BLOCK_DEFS_PATH = "mapconfig/blocks.json"
BLOCK_DEFS_FORMAT = "pymc_block_defs"

_CELLS = SECTION_SIZE ** 3


# ----------------------------------------------------------------------
# section 编解码
# ----------------------------------------------------------------------


def _encode_section(cells):
    """把一个 section 的方块字典编成 JSON 可序列化的对象。

    Args:
        cells: {(lx, ly, lz): block_id}，局部坐标 0..15，不含 0 的格子可省略。

    Returns:
        {"fill": id} 或 {"p": [...], "rle": [...]}
    """
    ids = sorted({0} | set(cells.values()))

    if len(ids) == 1:
        return {"fill": ids[0]}

    remap = {v: k for k, v in enumerate(ids)}

    # 按 YZX 序摊平成 4096 个调色板下标
    flat = []
    for y in range(SECTION_SIZE):
        for z in range(SECTION_SIZE):
            for x in range(SECTION_SIZE):
                flat.append(remap[cells.get((x, y, z), 0)])

    # 游程编码
    rle = []
    prev = flat[0]
    run = 1
    for v in flat[1:]:
        if v == prev:
            run += 1
        else:
            rle.append(run)
            rle.append(prev)
            prev = v
            run = 1
    rle.append(run)
    rle.append(prev)

    return {"p": ids, "rle": rle}


def _decode_section(sec):
    """把一个 section 对象解成 4096 长的方块 id 列表（YZX 序）。"""
    if "fill" in sec:
        return [sec["fill"]] * _CELLS

    p = sec["p"]
    rle = sec["rle"]

    if len(rle) % 2 != 0:
        raise ValueError(f"rle length must be even, got {len(rle)}")

    out = []
    for i in range(0, len(rle), 2):
        count = rle[i]
        idx = rle[i + 1]
        if not 0 <= idx < len(p):
            raise ValueError(f"palette index {idx} out of range 0..{len(p) - 1}")
        out.extend([p[idx]] * count)

    if len(out) != _CELLS:
        raise ValueError(f"run lengths sum to {len(out)}, expected {_CELLS}")

    return out


def _parse_section_key(key):
    parts = key.split(",")
    if len(parts) != 3:
        raise ValueError(f"bad section key {key!r}, expect 'sx,sy,sz'")
    return tuple(int(p) for p in parts)


# ----------------------------------------------------------------------
# 从方块字典编码整个场景
# ----------------------------------------------------------------------


def encode(blocks, generator="PyMC", block_defs=BLOCK_DEFS_PATH):
    """把方块字典编成完整的场景对象。

    Args:
        blocks: {(wx, wy, wz): block_id}，只需包含非空气方块。
        generator: 写进文件的产出者标识。
        block_defs: 共享方块定义文件的相对路径，只记路径不内嵌内容。

    Returns:
        可直接 json.dump 的字典。
    """
    # 按 section 分组
    grouped = {}
    for (wx, wy, wz), bid in blocks.items():
        if bid == 0:
            continue
        sp = (
            math.floor(wx / SECTION_SIZE),
            math.floor(wy / SECTION_SIZE),
            math.floor(wz / SECTION_SIZE),
        )
        local = (wx % SECTION_SIZE, wy % SECTION_SIZE, wz % SECTION_SIZE)
        grouped.setdefault(sp, {})[local] = bid

    sections = OrderedDict()
    used_ids = set()
    count = 0
    min_xyz = [None, None, None]
    max_xyz = [None, None, None]

    for sp in sorted(grouped):
        cells = grouped[sp]
        sections[f"{sp[0]},{sp[1]},{sp[2]}"] = _encode_section(cells)
        used_ids.update(cells.values())
        count += len(cells)

        for local, _ in cells.items():
            w = (
                sp[0] * SECTION_SIZE + local[0],
                sp[1] * SECTION_SIZE + local[1],
                sp[2] * SECTION_SIZE + local[2],
            )
            for i in range(3):
                if min_xyz[i] is None or w[i] < min_xyz[i]:
                    min_xyz[i] = w[i]
                if max_xyz[i] is None or w[i] > max_xyz[i]:
                    max_xyz[i] = w[i]

    if count == 0:
        min_xyz = [0, 0, 0]
        max_xyz = [0, 0, 0]

    return {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "generator": generator,
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "coordinate_system": {
            "axes": "right-handed, +X east, +Y up, +Z south",
            "unit": "1 block = 1 unit cube",
            "block_origin": "integer world coordinate of the block's center",
        },
        "block_defs": block_defs,
        "section_size": SECTION_SIZE,
        "order": ORDER,
        "bounds": {"min": min_xyz, "max": max_xyz},
        "block_count": count,
        "section_count": len(sections),
        "used_block_ids": sorted(used_ids),
        "sections": sections,
    }


def _check_header(doc):
    """校验场景对象的头部字段，不认识的直接报错而不是猜。"""
    if doc.get("format") != FORMAT_NAME:
        raise ValueError(f"unexpected format {doc.get('format')!r}, expect {FORMAT_NAME!r}")
    if doc.get("version") != FORMAT_VERSION:
        raise ValueError(f"unsupported version {doc.get('version')!r}")

    size = doc.get("section_size", SECTION_SIZE)
    if size != SECTION_SIZE:
        raise ValueError(f"unsupported section_size {size}, this decoder only handles {SECTION_SIZE}")

    order = doc.get("order", ORDER)
    if order != ORDER:
        raise ValueError(f"unsupported order {order!r}, this decoder only handles {ORDER!r}")


def decode(doc):
    """把场景对象解成 {(wx, wy, wz): block_id}，只含非空气方块。

    给外部工具和校验用。游戏内加载走 load_world，那条路径直接写进
    chunk.blocks 数组，不经过这个中间字典。
    """
    _check_header(doc)

    blocks = {}
    for key, sec in doc["sections"].items():
        sx, sy, sz = _parse_section_key(key)
        flat = _decode_section(sec)

        i = 0
        base_x = sx * SECTION_SIZE
        base_y = sy * SECTION_SIZE
        base_z = sz * SECTION_SIZE
        for y in range(SECTION_SIZE):
            for z in range(SECTION_SIZE):
                for x in range(SECTION_SIZE):
                    v = flat[i]
                    i += 1
                    if v:
                        blocks[(base_x + x, base_y + y, base_z + z)] = v

    declared = doc.get("block_count")
    if declared is not None and declared != len(blocks):
        raise ValueError(f"block_count says {declared} but decoded {len(blocks)}")

    return blocks


# ----------------------------------------------------------------------
# 文件读写
# ----------------------------------------------------------------------


def save_file(blocks, path, generator="PyMC", indent=None, block_defs=BLOCK_DEFS_PATH):
    """编码并写入文件，返回 (方块数, 路径)。"""
    doc = encode(blocks, generator=generator, block_defs=block_defs)

    dir_name = os.path.dirname(os.path.abspath(path))
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"), indent=indent)

    return doc["block_count"], path


def load_file(path):
    """读取文件并解码，返回 {(wx, wy, wz): block_id}。"""
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    return decode(doc)


# ----------------------------------------------------------------------
# 共享方块定义
# ----------------------------------------------------------------------


def load_block_defs(path=BLOCK_DEFS_PATH):
    """读取 mapconfig/blocks.json，返回 {block_id: 定义字典}。

    这份文件由 gen_block_defs.py 从 mapconfig/blocks.mcpy 生成，内容与场景无关。
    """
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)

    if doc.get("format") != BLOCK_DEFS_FORMAT:
        raise ValueError(
            f"unexpected format {doc.get('format')!r}, expect {BLOCK_DEFS_FORMAT!r}"
        )

    return {int(k): v for k, v in doc["blocks"].items()}


def resolve_block_defs(doc, base_dir=".", required=False):
    """按场景文件里的 block_defs 字段找到并读取共享定义。

    Args:
        doc: 已解析的场景对象。
        base_dir: 解析相对路径时的基准目录。
        required: True 时找不到就报错，False 时返回 None。
    """
    rel = doc.get("block_defs", BLOCK_DEFS_PATH)
    path = rel if os.path.isabs(rel) else os.path.join(base_dir, rel)

    if not os.path.exists(path):
        if required:
            raise FileNotFoundError(f"block defs not found: {path}")
        return None

    return load_block_defs(path)


# ----------------------------------------------------------------------
# 与游戏内 World 对象对接
# ----------------------------------------------------------------------


def palette_from_world(world):
    """从 world.block_types 提取方块类型说明，形状与 mapconfig/blocks.json 的
    blocks 段一致。

    场景文件不内嵌这些内容，这个函数用于把运行中的 world 与共享定义做比对，
    见 check_block_defs。
    """
    source = {}
    for bid, bt in enumerate(world.block_types):
        if bid == 0 or bt is None:
            continue
        model_name = getattr(bt.model, "__name__", "models.cube")
        source[bid] = {
            "name": bt.name,
            "model": model_name.rsplit(".", 1)[-1],
            "is_cube": bool(bt.is_cube),
            "transparent": bool(bt.transparent),
            "glass": bool(bt.glass),
            "textures": dict(bt.block_face_textures),
        }
    return source


def check_block_defs(world, path=BLOCK_DEFS_PATH):
    """比对运行中的 world 与 mapconfig/blocks.json，返回不一致的方块 id 列表。

    两边都源自 mapconfig/blocks.mcpy，不一致说明 blocks.mcpy 改过之后
    忘了重跑 gen_block_defs.py。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{path} not found, run: uv run python gen_block_defs.py"
        )

    shared = load_block_defs(path)
    live = palette_from_world(world)

    bad = []
    for bid in sorted(set(shared) | set(live)):
        if shared.get(bid) != live.get(bid):
            bad.append(bid)
    return bad


def blocks_from_world(world):
    """把 world 里所有非空气方块导出成字典。"""
    import config

    blocks = {}
    for cp, c in world.chunks.items():
        ox = cp[0] * config.CHUNK_WIDHT
        oy = cp[1] * config.CHUNK_HEIGHT
        oz = cp[2] * config.CHUNK_LENGHTH
        for x in range(config.CHUNK_WIDHT):
            col = c.blocks[x]
            for y in range(config.CHUNK_HEIGHT):
                row = col[y]
                for z in range(config.CHUNK_LENGHTH):
                    v = row[z]
                    if v:
                        blocks[(ox + x, oy + y, oz + z)] = v
    return blocks


def save_world(world, path, generator="PyMC"):
    """把游戏世界写成场景文件，返回 (方块数, 路径)。

    只写方块 id，方块类型说明在 mapconfig/blocks.json 里。
    """
    return save_file(
        blocks_from_world(world),
        path,
        generator=generator,
    )


def load_world(world, path, clear=True):
    """把场景文件读进游戏世界，返回方块数。

    直接从 section 写进 chunk.blocks 数组，不经过 {(x,y,z): id} 中间字典，
    也不走 _put_block_raw 的逐格函数调用。110 万方块的存档能省掉几百毫秒的
    坐标换算。末尾统一 build_meshs()，不做逐块网格更新。
    """
    import chunk as chunk_mod
    import config

    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)

    _check_header(doc)

    if clear:
        # 丢弃前先释放 GL 缓冲，否则句柄在驱动侧泄漏
        for c in world.chunks.values():
            c.dispose()
        world.chunks = {}

    # 一个 chunk 在 y 方向装得下几个 section
    secs_per_chunk_y = config.CHUNK_HEIGHT // SECTION_SIZE
    max_id = len(world.block_types) - 1

    count = 0
    for key, sec in doc["sections"].items():
        sx, sy, sz = _parse_section_key(key)
        flat = _decode_section(sec)

        # section 坐标 -> chunk 坐标 + chunk 内的 y 段号
        cy, sub_y = divmod(sy, secs_per_chunk_y)
        cp = (sx, cy, sz)

        cur = world.chunks.get(cp)
        if cur is None:
            cur = chunk_mod.Chunk(world, cp)
            world.chunks[cp] = cur

        base_y = sub_y * SECTION_SIZE
        cells = cur.blocks

        i = 0
        for ly in range(SECTION_SIZE):
            wy = base_y + ly
            for lz in range(SECTION_SIZE):
                for lx in range(SECTION_SIZE):
                    v = flat[i]
                    i += 1
                    if v:
                        # 负数也要拦：block_types[-1] 是负索引，
                        # 会拿到列表末尾元素而不是报错
                        if v < 0 or v > max_id or world.block_types[v] is None:
                            raise ValueError(
                                f"block id {v} in section {key} is not defined "
                                f"in mapconfig/blocks.mcpy"
                            )
                        cells[lx][wy][lz] = v
                        count += 1

    world.build_meshs()

    declared = doc.get("block_count")
    if declared is not None and declared != count:
        raise ValueError(f"block_count says {declared} but loaded {count}")

    return count
