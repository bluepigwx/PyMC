# PyMC 场景文件 Schema（给 AI 生成场景用）

> 用途：生成一份合法的 `pymc_scene` v1 JSON 场景文件，可直接被 PyMC 加载
> （游戏内 `load_scene` / 启动参数 `python main.py <文件>`）。
> 实现代码：`scene_serializer.py`；真实示例：`save/v1/world.json`。
> 本文与 `mapv1.md` 的区别：mapv1 是设计文档，本文只写生成时必须遵守的规则。

---

## 1. 顶层结构

```json
{
  "format": "pymc_scene",
  "version": 1,
  "generator": "<生成者名字>",
  "saved_at": "2026-09-19T14:00:00+0800",
  "coordinate_system": {
    "axes": "right-handed, +X east, +Y up, +Z south",
    "unit": "1 block = 1 unit cube",
    "block_origin": "integer world coordinate of the block's center"
  },
  "block_defs": "mapconfig/blocks.json",
  "section_size": 16,
  "order": "yzx",
  "bounds": { "min": [0, 0, 0], "max": [15, 9, 15] },
  "block_count": 2119,
  "section_count": 4,
  "used_block_ids": [1, 2, 45],
  "sections": { ... }
}
```

| 字段 | 必需 | 规则 |
|---|---|---|
| `format` | 是 | 固定 `"pymc_scene"`，其他值加载时报错 |
| `version` | 是 | 固定 `1` |
| `section_size` | 是 | 固定 `16` |
| `order` | 是 | 固定 `"yzx"` |
| `block_defs` | 是 | 固定 `"mapconfig/blocks.json"` |
| `sections` | 是 | 场景数据主体，见第 3 节 |
| `generator` | 否 | 生成者标识，任意字符串 |
| `saved_at` | 否 | 时间字符串 |
| `coordinate_system` | 否 | 说明性字段，照抄上面的值即可 |
| `bounds` | 否 | 非空气方块的包围盒，闭区间。**写了就必须和内容一致** |
| `block_count` | 否 | 非空气方块总数。**写了就必须一致**，加载器会核对，不等直接报错 |
| `section_count` | 否 | `sections` 的条目数 |
| `used_block_ids` | 否 | 用到的方块 id 升序列表 |

拿不准的可选字段宁可不写，也不要写一个对不上的值——`bounds` 和 `block_count`
会被加载器当作校验依据。

## 2. 坐标系

- 右手系：`+X` 东、`+Y` 上、`+Z` 南
- 整数世界坐标表示方块的**中心**，方块占据 `[x-0.5, x+0.5]` 区间
- 一个方块一格，`y` 向上增长

## 3. sections：场景数据主体

世界被切成 16×16×16 的 section。`sections` 是对象，key 是 section 坐标：

```
sx = floor(world_x / 16)    # 向下取整，负数坐标也一样：-1 // 16 == -1
sy = floor(world_y / 16)
sz = floor(world_z / 16)
key = "sx,sy,sz"            # 逗号分隔，无空格，如 "-1,0,-1"
```

**只有含非空气方块的 section 才出现。** 全空气的 section 不写，加载时视为空气。

每个 section 两种形态二选一：

### 形态 A：`fill` —— 4096 格全是同一种方块

```json
"0,1,0": { "fill": 1 }
```

整段都是方块 id 1（Stone）。地下实心区、水体、大片平地用这个。
`{"fill": 0}` 合法但没必要写（全空气直接省略整个 key）。

### 形态 B：`p` + `rle` —— 局部调色板 + 游程编码

```json
"-1,0,-1": { "p": [0, 1, 2, 45], "rle": [256, 2, 136, 0, 3, 1, 13, 0, "..."] }
```

**`p`（palette）**：这个 section 里出现过的方块 id，**升序，第 0 项必须是 0**（空气）。

**`rle`**：扁平数组 `[个数, palette下标, 个数, palette下标, ...]`。注意第二个元素是
**`p` 数组的下标，不是方块 id**。上例开头 `256, 2` 表示前 256 格是 `p[2]`（即 id 2，Grass）。

硬约束（加载器逐条校验，违反即报错）：

1. `rle` 长度必须是偶数
2. 所有"个数"相加必须恰好等于 `4096`（= 16³）
3. 每个 palette 下标满足 `0 <= idx < len(p)`
4. 展开后的方块 id 必须在 1..84 范围内有定义（0 是空气）

### YZX 展开顺序

`rle` 展开成长度 4096 的下标序列后，第 `i` 格对应的 section 内局部坐标：

```
ly = i // 256        # y 最慢变化
lz = (i % 256) // 16
lx = i % 16          # x 最快变化
```

世界坐标：`world = (sx*16 + lx, sy*16 + ly, sz*16 + lz)`。

**生成时的实操写法**：对每个 section 建一个 4096 长的数组 `flat`，按
`flat[ly*256 + lz*16 + lx] = palette_index` 填入，然后把相邻相同值合并成游程对。

## 4. 方块 id 表（共 84 种，id 0 = 空气）

来源 `mapconfig/blocks.json`。"形状"列影响摆放效果：cube 是满格立方体；
plant/torch/slab/stairs/flat 等是部分形状（不占满一格）；transparent 的方块会透光。

### 基础材料（cube，实心）

| id | 名称 | id | 名称 |
|---|---|---|---|
| 1 | Stone 石头 | 2 | Grass 草方块 |
| 3 | Dirt 泥土 | 4 | Cobblestone 圆石 |
| 5 | Planks 木板 | 7 | Bedrock 基岩 |
| 12 | Sand 沙子 | 13 | Gravel 沙砾 |
| 17 | Log 原木 | 19 | Sponge 海绵 |
| 41 | Gold Block 金块 | 42 | Iron Block 铁块 |
| 43 | Double Slab 双层台阶 | 45 | Bricks 砖块 |
| 46 | TNT | 47 | Bookshelf 书架 |
| 48 | Mossy Cobblestone 苔石 | 49 | Obsidian 黑曜石 |
| 57 | Diamond Block 钻石块 | 58 | Crafting Table 工作台 |
| 61 | Furnace 熔炉 | 62 | Lit Furnace 燃烧的熔炉 |
| 64 | Wooden Door 木门 | 71 | Iron Door 铁门 |
| 80 | Snow Block 雪块 | 82 | Clay 黏土 |
| 84 | Jukebox 唱片机 | 54 | Chest 箱子 |

### 矿石（cube，实心）

| id | 名称 |
|---|---|
| 14 | Gold Ore 金矿石 |
| 15 | Iron Ore 铁矿石 |
| 16 | Coal Ore 煤矿石 |
| 56 | Diamond Ore 钻石矿石 |
| 73 / 74 | Redstone Ore 红石矿石（普通/发光） |

### 布料（cube，实心，16 色）

| id | 名称 |
|---|---|
| 21..36 | Red / Orange / Yellow / Lime / Green / Aqua / Cyan / Blue / Purple / Indigo / Violet / Magenta / Pink / Black / Grey / White Cloth |

### 透明/透光（cube 但透光）

| id | 名称 | 备注 |
|---|---|---|
| 8 / 9 | Water 水（流动/静止） | liquid |
| 10 / 11 | Lava 岩浆（流动/静止） | liquid |
| 18 | Leaves 树叶 | leaves |
| 20 | Glass 玻璃 | glass |
| 52 | Mob Spawner 刷怪笼 | leaves 形状 |
| 79 | Ice 冰 | tinted_glass |

### 部分形状（不占满一格，transparent）

| id | 名称 | 模型 |
|---|---|---|
| 6 | Sapling 树苗 | plant |
| 37 | Yellow Flower 黄花 | plant |
| 38 | Red Rose 红玫瑰 | plant |
| 39 / 40 | Brown / Red Mushroom 蘑菇 | plant |
| 44 | Slab 半砖 | slab |
| 50 | Torch 火把 | torch |
| 51 | Fire 火 | fire |
| 53 / 67 | Wooden / Cobblestone Stairs 楼梯 | stairs |
| 55 | Redstone Wire 红石线 | flat |
| 59 | Crops 作物 | crop |
| 60 | Soil 耕地 | soil |
| 63 | Sign Post 告示牌 | sign_post |
| 65 | Ladder 梯子 | ladder |
| 66 | Rails 铁轨 | flat |
| 68 | Sign 墙上告示牌 | sign |
| 69 | Lever 拉杆 | lever |
| 70 / 72 | Stone / Wooden Pressure Plate 压力板 | pressure_plate |
| 75 / 76 | Redstone Torch 红石火把（亮/灭） | torch |
| 77 | Stone Button 石头按钮 | button |
| 78 | Snow 雪片 | snow |
| 81 | Cactus 仙人掌 | cactus |
| 83 | Sugar Cane 甘蔗 | plant |

## 5. 完整最小示例

一个 16×1×16 的草地平台（y=0 一层草，其余空气）：

```json
{
  "format": "pymc_scene",
  "version": 1,
  "generator": "example",
  "block_defs": "mapconfig/blocks.json",
  "section_size": 16,
  "order": "yzx",
  "bounds": { "min": [0, 0, 0], "max": [15, 0, 15] },
  "block_count": 256,
  "section_count": 1,
  "used_block_ids": [2],
  "sections": {
    "0,0,0": { "p": [0, 2], "rle": [256, 1, 3840, 0] }
  }
}
```

解读：`rle` 前 256 格是 `p[1]`（id 2 草方块）——按 YZX 序正好是 `ly=0` 那一整层；
后 3840 格是 `p[0]`（空气）。

## 6. 生成步骤建议

1. 先按世界坐标列出所有非空气方块 `(x, y, z, block_id)`
2. 按 `floor(coord / 16)` 分组到 section
3. 每个 section：
   - 收集出现的 id，加上 0，升序排成 `p`
   - 建 4096 长数组，`flat[ly*256 + lz*16 + lx] = p.index(id)`，空格填 0
   - 全部相同 → 写 `{"fill": id}`；否则相邻相同值合并成 `rle`
4. 统计 `bounds` / `block_count` / `used_block_ids`，要么写正确，要么不写
5. 输出时用紧凑分隔符 `json.dump(..., separators=(",", ":"))`，不要 indent

## 7. 自检清单（生成后逐条过）

- [ ] `format` / `version` / `section_size` / `order` 四个字段值完全等于规定值
- [ ] 每个 section key 是 `"sx,sy,sz"` 三整数逗号分隔，负数允许
- [ ] 全空气 section 没有写进 `sections`
- [ ] 每个 `p` 数组第 0 项是 0 且整体升序
- [ ] 每个 `rle` 长度为偶数，个数之和 = 4096，下标不越界
- [ ] 用到的 id 都在第 4 节的表里（1..84）
- [ ] `block_count` 若写了，等于各 section 非空气格数之和
- [ ] 没有负数 id（加载器会报错）

## 8. 几何自检（生成后必须做）

编码自检（解码往返逐格一致）只证明文件没写错，证明不了设计没窟窿。
几何错误几乎都出在**部件接缝处**（墙与屋顶、楼层之间、楼梯与平台、地基与地面），
因为生成时每个部件各算各的坐标，接缝谁都没管。生成后逐条过：

1. **支撑检查**：所有"应该落在别的东西上面"的部件，其底面每个方块的正下方一格
   必须有方块（有意悬空的除外）。
   ```python
   unsupported = [(x, y, z) for x, y, z in part_bottoms if (x, y - 1, z) not in blocks]
   assert not unsupported
   ```
2. **竖直剖面抽查**：取有代表性的柱子（角、面中心），把该柱 y 从低到高的方块
   列出来，实体段内不允许断档。注意**空心内部、门洞、窗户是设计内的空**，
   抽查要避开或排除这些位置，只查实体段。
3. **坐标从锚点推导**：部件 B 落在 A 上时，B 的底写成 `A的顶 + 1` 的推导式，
   不要各写各的独立常量。各写各的，接缝处必出错。

## 9. 常见错误

| 错误 | 后果 |
|---|---|
| `rle` 里直接写方块 id 而不是 `p` 的下标 | 下标越界报错，或渲染成错误方块 |
| 游程个数之和不是 4096 | 加载报错 `run lengths sum to N` |
| 把 `{"fill": 0}` 的空 section 写进文件 | 不报错但多余，空 section 应该整个省略 |
| 按 XZY 顺序展开（y 最快） | 场景立体结构被打散成竖条，能加载但内容全错 |
| 写了 `block_count` 但和实际不一致 | 加载最后一步校验报错，整个场景不生效 |
