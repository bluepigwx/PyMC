---
name: pymc-scene-builder
description: 通过 PyMC 游戏进程内置的 MCP 服务生成体素场景（Minecraft 风格）。当需要在运行中的 PyMC 世界里建造建筑、批量放置方块、生成/重置/加载场景、或做体素场景实验迭代时使用本技能。
---

# PyMC 体素场景生成

PyMC 是一个 Python + OpenGL 的体素渲染器。游戏进程启动后内置一个 MCP 服务
（HTTP，`http://127.0.0.1:8765/mcp`），AI Agent 通过它读写世界。

## 前置条件

- PyMC 游戏进程正在运行（服务随游戏启动、随游戏退出；连接失败 = 窗口关了）
- MCP 客户端配置：`{"mcpServers": {"pymc": {"type": "http", "url": "http://127.0.0.1:8765/mcp"}}}`
- 没有 MCP 客户端时，用 `scripts/mcp_call.py` 从命令行调（依赖 fastmcp）

## 工具速查（共 11 个）

| 工具 | 干什么 | 什么时候用 |
|---|---|---|
| `get_game_status` | 游戏存活 + 相机 + 计数器 | 每次会话先调，确认服务活着 |
| `get_scene_info` | 相机、方块统计、包围盒 | **动手前必调**，确认当前世界状态 |
| `list_block_types` | 84 种方块 id / 名字 / 几何模型 | 选方块时查 |
| `fill_region` / `fill_regions` | 填充长方体（带 exclude/override） | 盒子能拼出来的结构，首选 |
| `place_blocks` | 逐点放置 | 零散点，量大别用 |
| `clear_region` | 长方体清空 | 局部清场 |
| `reset_scene` | **一键重建**：清场 + 重生草地 + 可选叠加场景文件 | 每次实验的起点 |
| `reset_world` | 清场 + 重生草地 | 只要干净草地 |
| `save_scene` / `load_scene` | 场景文件存取 | 存档、复现、一次性加载 |

## 两条生成路线

### 路线 A：fill_regions 直接建造

适合中小规模、能拆成一批长方体的结构（房子、城墙、金字塔）。

- Region 参数：`type, x_min..z_max`（闭区间）+ `exclude`（挖洞：门窗）+ `override`（换材质：墙上镶玻璃）
- 一次 `fill_regions` 可以发几十上百个区域，游戏统一重建一次网格，比多次 `fill_region` 快
- 单次调用方块数上限 200000（`PYMC_MAX_BLOCKS` 可调）

### 路线 B：场景 JSON 文件 + 一次性加载（推荐用于复杂场景）

适合大型、复杂、需要存档复用的场景。流程：

1. 按 `reference/scene_format.md` 的格式生成场景 JSON（16³ section + 调色板 + RLE）
2. 用 `scripts/scene_kit.py` 编码，**不要手写 RLE**：
   ```python
   import scene_kit
   blocks = {}  # {(x,y,z): block_id}，只放非空气
   # ... 生成方块 ...
   scene_kit.write_scene(blocks, "my_scene.json")
   ```
3. 用 `scripts/validate_scene.py` 校验（规则与游戏内加载器一致）
4. `reset_scene(path=...)` 一次调用完成"清场 + 草地 + 加载"

## 标准工作流

```
1. get_game_status        确认服务活着
2. get_scene_info         确认当前世界状态（空地？有旧建筑？相机在哪？）
3. 设计场景，选方块 id（list_block_types 或 reference/scene_format.md 第 4 节）
4. 生成（路线 A 或 B）
5. 几何自检（见下节，路线 B 用脚本做，路线 A 在展开坐标后做）
6. 写入世界（fill_regions / reset_scene+load_scene）
7. get_scene_info 验证：方块总数、包围盒、按类型统计是否符合设计
8. save_scene 存档（值得保留时）
```

反复实验时，每次只改第 3~6 步，第 6 步固定用 `reset_scene` 回到干净状态。

## 几何自检（每次生成必须做）

几何错误几乎都出在**部件接缝处**（墙与屋顶、楼层之间、楼梯与平台、地基与地面），
因为生成时每个部件各算各的坐标，接缝没人管。

1. **支撑检查**：所有"应落在别的东西上面"的部件，其底面每个方块正下方一格
   必须有方块（有意悬空的除外）。用 `scene_kit.support_check(blocks, bottoms)`。
2. **竖直剖面抽查**：用 `scene_kit.column_profile(blocks, x, z)` 抽几根有代表性的
   柱子（角、面中心）眼看断档。**空心内部、门洞、窗户是设计内的空**，
   抽查要避开，只查实体段。
3. **坐标从锚点推导**：部件 B 落在 A 上时，B 的底写成 `A的顶 + 1`，
   不要各写各的独立常量。
4. 编码自检 ≠ 几何自检：文件格式合法不代表设计没窟窿，两个都要做。

## 常识与边界

- 坐标系：右手系，+X 东、+Y 上、+Z 南；整数坐标是方块**中心**
- 默认世界是平坦草地：`y=0` 一层草，x/z ∈ [-128, 127]，建造从 `y=1` 起
- 不要假设地表在哪：加载过存档的世界有真实地形，先 `get_scene_info` 看包围盒
- id 0 是空气：写入 0 = 删除该坐标方块
- 方块分两类几何：`cube` 是满格实心；`plant/torch/slab/stairs/flat` 等是部分形状；
  `glass/leaves/liquid` 透光。造承重墙用 cube，装饰另算
- MCP 工具经主线程队列执行，默认超时 120 秒（`PYMC_JOB_TIMEOUT`）；
  大批量写入期间游戏画面会卡一下，正常

## 常见错误

| 错误 | 后果 |
|---|---|
| 手写 RLE 而不是用编码器 | 游程和不为 4096 / 下标越界，加载报错 |
| 给部件各写独立坐标常量 | 接缝处悬空或穿插（最典型的几何错误） |
| 用 `load_scene(clear=true)` 建场景 | 连草地一起清掉，建筑悬空 |
| 超 200000 方块一次调用 | 工具报错，拆批或调 `PYMC_MAX_BLOCKS` |
| 场景文件里写负数 id | 加载报错 |

## 本包内容

```
SKILL.md                      本文件
scripts/scene_kit.py          场景 JSON 编码/解码/校验/几何检查库（零依赖）
scripts/validate_scene.py     场景文件校验 CLI（规则与游戏内加载器一致）
scripts/mcp_call.py           MCP 工具命令行调用器（依赖 fastmcp）
reference/scene_format.md     场景格式规范 + 84 种方块 id 表
```
