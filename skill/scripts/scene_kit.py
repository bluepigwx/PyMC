"""PyMC 场景格式（pymc_scene v1）的独立读写/校验库。

零第三方依赖，供 AI Agent 在 PyMC 工程之外生成和校验场景文件。
格式规范见同目录 reference/scene_format.md。

API:
    write_scene(blocks, path)      把 {(x,y,z): block_id} 写成场景文件
    read_scene(path)               读场景文件成 {(x,y,z): block_id}
    encode(blocks)                 blocks 字典 -> 场景对象（不落地）
    decode(doc)                    场景对象 -> blocks 字典
    validate(doc)                  校验场景对象，返回错误列表（空 = 合法）
    support_check(blocks, bottoms) 几何检查：底面方块正下方是否有支撑
    column_profile(blocks, x, z)   几何检查：一根柱子的竖直剖面 [(y, id), ...]
"""

from __future__ import annotations

import json
import os
import time

FORMAT_NAME = "pymc_scene"
FORMAT_VERSION = 1
SECTION_SIZE = 16
ORDER = "yzx"
BLOCK_DEFS_PATH = "mapconfig/blocks.json"

# 当前 PyMC 方块 id 上限（mapconfig/blocks.json 定义 1..84，0 是空气）
MAX_BLOCK_ID = 84

_CELLS = SECTION_SIZE ** 3


# ----------------------------------------------------------------------
# 编码
# ----------------------------------------------------------------------

def _encode_section(cells):
    ids = sorted({0} | set(cells.values()))
    if len(ids) == 1:
        return {"fill": ids[0]}

    remap = {v: k for k, v in enumerate(ids)}
    flat = []
    for y in range(SECTION_SIZE):
        for z in range(SECTION_SIZE):
            for x in range(SECTION_SIZE):
                flat.append(remap[cells.get((x, y, z), 0)])

    rle = []
    prev, run = flat[0], 1
    for v in flat[1:]:
        if v == prev:
            run += 1
        else:
            rle += [run, prev]
            prev, run = v, 1
    rle += [run, prev]
    return {"p": ids, "rle": rle}


def encode(blocks, generator="scene-kit", block_defs=BLOCK_DEFS_PATH):
    """{(wx, wy, wz): block_id}（只需非空气）-> 场景对象。"""
    grouped = {}
    for (wx, wy, wz), bid in blocks.items():
        if bid == 0:
            continue
        sp = (wx // SECTION_SIZE, wy // SECTION_SIZE, wz // SECTION_SIZE)
        local = (wx % SECTION_SIZE, wy % SECTION_SIZE, wz % SECTION_SIZE)
        grouped.setdefault(sp, {})[local] = bid

    sections = {}
    used, count = set(), 0
    lo, hi = [None] * 3, [None] * 3
    for sp in sorted(grouped):
        cells = grouped[sp]
        sections[f"{sp[0]},{sp[1]},{sp[2]}"] = _encode_section(cells)
        used.update(cells.values())
        count += len(cells)
        for lx, ly, lz in cells:
            w = (sp[0] * SECTION_SIZE + lx,
                 sp[1] * SECTION_SIZE + ly,
                 sp[2] * SECTION_SIZE + lz)
            for i in range(3):
                lo[i] = w[i] if lo[i] is None else min(lo[i], w[i])
                hi[i] = w[i] if hi[i] is None else max(hi[i], w[i])
    if count == 0:
        lo = hi = [0, 0, 0]

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
        "bounds": {"min": lo, "max": hi},
        "block_count": count,
        "section_count": len(sections),
        "used_block_ids": sorted(used),
        "sections": sections,
    }


def write_scene(blocks, path, generator="scene-kit"):
    """编码并写文件，返回 (方块数, 路径)。输出用紧凑分隔符。"""
    doc = encode(blocks, generator=generator)
    dir_name = os.path.dirname(os.path.abspath(path))
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    return doc["block_count"], path


# ----------------------------------------------------------------------
# 解码与校验
# ----------------------------------------------------------------------

def _decode_section(sec):
    if "fill" in sec:
        return [sec["fill"]] * _CELLS
    p, rle = sec["p"], sec["rle"]
    if len(rle) % 2 != 0:
        raise ValueError(f"rle length must be even, got {len(rle)}")
    out = []
    for i in range(0, len(rle), 2):
        count, idx = rle[i], rle[i + 1]
        if not 0 <= idx < len(p):
            raise ValueError(f"palette index {idx} out of range 0..{len(p) - 1}")
        out += [p[idx]] * count
    if len(out) != _CELLS:
        raise ValueError(f"run lengths sum to {len(out)}, expected {_CELLS}")
    return out


def validate(doc, max_block_id=MAX_BLOCK_ID):
    """校验场景对象，返回错误字符串列表。空列表 = 合法。

    规则与 PyMC 游戏内加载器一致：头部四字段精确匹配、rle 长度为偶数、
    游程个数之和 = 4096、调色板下标不越界、方块 id 在 1..max_block_id、
    block_count（若声明）与实际一致。
    """
    errors = []
    if doc.get("format") != FORMAT_NAME:
        errors.append(f"unexpected format {doc.get('format')!r}, expect {FORMAT_NAME!r}")
    if doc.get("version") != FORMAT_VERSION:
        errors.append(f"unsupported version {doc.get('version')!r}")
    if doc.get("section_size", SECTION_SIZE) != SECTION_SIZE:
        errors.append(f"unsupported section_size {doc.get('section_size')!r}")
    if doc.get("order", ORDER) != ORDER:
        errors.append(f"unsupported order {doc.get('order')!r}")
    if errors:
        return errors

    total = 0
    for key, sec in doc.get("sections", {}).items():
        parts = key.split(",")
        if len(parts) != 3 or not all(p.lstrip("-").isdigit() for p in parts):
            errors.append(f"bad section key {key!r}, expect 'sx,sy,sz'")
            continue
        try:
            flat = _decode_section(sec)
        except (ValueError, KeyError, TypeError) as e:
            errors.append(f"section {key}: {e}")
            continue
        for v in flat:
            if v:
                if not 1 <= v <= max_block_id:
                    errors.append(f"section {key}: undefined block id {v}")
                    break
                total += 1

    declared = doc.get("block_count")
    if declared is not None and declared != total:
        errors.append(f"block_count says {declared} but decoded {total}")
    return errors


def decode(doc):
    """场景对象 -> {(wx, wy, wz): block_id}（只含非空气）。非法直接抛异常。"""
    errors = validate(doc)
    if errors:
        raise ValueError("; ".join(errors))

    blocks = {}
    for key, sec in doc["sections"].items():
        sx, sy, sz = (int(p) for p in key.split(","))
        flat = _decode_section(sec)
        i = 0
        for y in range(SECTION_SIZE):
            for z in range(SECTION_SIZE):
                for x in range(SECTION_SIZE):
                    v = flat[i]
                    i += 1
                    if v:
                        blocks[(sx * SECTION_SIZE + x,
                                sy * SECTION_SIZE + y,
                                sz * SECTION_SIZE + z)] = v
    return blocks


def read_scene(path):
    """读场景文件成 {(x,y,z): block_id}。"""
    with open(path, "r", encoding="utf-8") as f:
        return decode(json.load(f))


# ----------------------------------------------------------------------
# 几何检查（与设计无关的通用件，规范第 8 节）
# ----------------------------------------------------------------------

def support_check(blocks, bottoms):
    """底面支撑检查。bottoms 是"应落在别的东西上面"的方块坐标列表，
    返回正下方一格没有方块的坐标列表（空 = 全部有着落）。
    有意悬空的部件不要把它的底面传进来。
    """
    return [(x, y, z) for x, y, z in bottoms if (x, y - 1, z) not in blocks]


def column_profile(blocks, x, z):
    """一根柱子的竖直剖面：[(y, block_id), ...] 按 y 升序。
    用来眼看断档。注意空心内部、门洞、窗户是设计内的空，
    判读时要排除，只查实体段。
    """
    return sorted((y, b) for (bx, y, bz), b in blocks.items()
                  if bx == x and bz == z)
