"""校验一份 pymc_scene v1 场景文件，打印统计信息。

用法:
    python validate_scene.py <scene.json>

退出码：0 = 合法，1 = 有错误。零第三方依赖。
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scene_kit import validate


def main():
    path = sys.argv[1]
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)

    errors = validate(doc)
    if errors:
        print(f"INVALID: {path}")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"OK: {path}")
    print(f"  block_count   {doc.get('block_count')}")
    print(f"  section_count {doc.get('section_count')}")
    print(f"  bounds        {doc.get('bounds')}")
    print(f"  used_ids      {doc.get('used_block_ids')}")
    print(f"  size          {os.path.getsize(path)} B")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    sys.exit(main())
