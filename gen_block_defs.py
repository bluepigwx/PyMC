"""从 data/blocks.mcpy 生成独立的方块定义文件 mapconfig/blocks.json。

场景文件不内嵌方块类型说明，改为引用这份共享定义。
这份文件的内容只依赖 data/blocks.mcpy 和 models/，跟具体场景无关。
改了 data/blocks.mcpy 之后要重跑一次。

用法:
    uv run python gen_block_defs.py

校验生成结果与运行中的游戏是否一致：
    scene_format.check_block_defs(world)
"""

import json
import os
import re
import sys
import time

import models

SRC = os.path.join("data", "blocks.mcpy")
OUT = os.path.join("mapconfig", "blocks.json")

DEFS_NAME = "pymc_block_defs"
DEFS_VERSION = 1

_ID = re.compile(r"^\s*(\d+)\s*:(.*)$")
_NAME = re.compile(r'name\s+"([^"]*)"')
_SAMEAS = re.compile(r"sameas\s+(\d+)")
_MODEL = re.compile(r"model\s+models\.(\w+)")
_TEX = re.compile(r"texture\.(\w+)\s+(\S+?)(?:,|$)")


def parse_blocks_mcpy(path=SRC):
    """解析 data/blocks.mcpy，返回 {id: 定义字典}。

    解析规则与 world.World._load_block_type 保持一致：
      - 默认 name="Unknown"、model=models.cube、textures={"all": "unknown"}
      - sameas 先继承，后面的属性可以覆盖
      - transparent / is_cube / glass 不猜，直接读 models/<名>.py 的模块常量
    """
    table = {}
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue

            m = _ID.match(line)
            if not m:
                print(f"  warn: line {lineno} not recognized: {line.strip()[:60]}",
                      file=sys.stderr)
                continue

            bid = int(m.group(1))
            props = m.group(2)

            # 默认值与 world.py 一致：textures 初始含 {"all": "unknown"}
            name = "Unknown"
            model_name = "cube"
            tex = {"all": "unknown"}

            sameas = _SAMEAS.search(props)
            if sameas:
                base_id = int(sameas.group(1))
                base = table.get(base_id)
                if base is None:
                    raise ValueError(f"line {lineno}: sameas {base_id} not defined yet")
                name = base["name"]
                model_name = base["model"]
                tex = dict(base["textures"])

            nm = _NAME.search(props)
            if nm:
                name = nm.group(1)

            md = _MODEL.search(props)
            if md:
                model_name = md.group(1)

            for face, t in _TEX.findall(props):
                tex[face] = t.strip()

            model = getattr(models, model_name, None)
            if model is None:
                raise ValueError(f"line {lineno}: unknown model models.{model_name}")

            table[bid] = {
                "name": name,
                "model": model_name,
                "is_cube": bool(model.is_cube),
                "transparent": bool(model.transparent),
                "glass": bool(model.glass),
                "textures": tex,
            }

    return table


def main():
    if not os.path.exists(SRC):
        print(f"{SRC} not found", file=sys.stderr)
        return 1

    table = parse_blocks_mcpy()

    doc = {
        "format": DEFS_NAME,
        "version": DEFS_VERSION,
        "generator": "gen_block_defs.py",
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": SRC.replace("\\", "/"),
        "note": (
            "Shared block type definitions for pymc_scene files. "
            "Scene files reference block ids; look them up here. "
            "id 0 is air and is not listed. "
            "Texture files live in textures/<name>.png"
        ),
        "texture_dir": "textures",
        "face_keys": [
            "all", "sides", "x", "y", "z",
            "top", "bottom", "front", "back", "left", "right",
        ],
        "block_count": len(table),
        "blocks": {str(k): table[k] for k in sorted(table)},
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)

    size = os.path.getsize(OUT)
    used_models = sorted({v["model"] for v in table.values()})
    textures = sorted({t for v in table.values() for t in v["textures"].values()})

    print(f"wrote {OUT}")
    print(f"  block types  {len(table)}  (id {min(table)}..{max(table)})")
    print(f"  models       {len(used_models)}: {', '.join(used_models)}")
    print(f"  textures     {len(textures)} 个贴图名")
    print(f"  size         {size} B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
