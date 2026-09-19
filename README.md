# PyMC

用 Python + OpenGL 写的仿 Minecraft 体素渲染器。支持本地鼠标建造，也支持 Agent
通过 MCP 或 TCP 远程操作世界。

## 环境

依赖用 uv 管理，Python >= 3.11。

```bash
uv sync
```

## 启动

```bash
# 载入默认场景（save/v1/world.json 存在时自动加载）
uv run python main.py

# 载入指定场景
uv run python main.py 某个场景.json

# 忽略场景文件，生成一片平坦草地
uv run python main.py --default
```

## 操作

| 键 | 作用 |
|---|---|
| `WASD` | 水平移动 |
| `Q` / `E` | 上升 / 下降 |
| 鼠标 | 转视角 |
| 左键 | 放置手持方块 |
| 右键 | 删除方块 |
| `1`-`9` | 切换手持方块 |
| `ESC` | 锁定 / 解锁鼠标 |
| `` ` `` | 打开聊天框 |
| `H` | 回到出生点 |
| `R` | 重置为默认草地 |
| `K` | 存档 |
| `L` | 读档 |

## 两个服务端口

游戏进程启动后会同时开两个口子，都是给 Agent 用的。

**MCP over HTTP，`127.0.0.1:8765/mcp`**

跑在游戏进程内的后台线程里，随游戏启动、随游戏退出。实现见 `mcp_server/`。

MCP 客户端配置：

```json
{
  "mcpServers": {
    "pymc": { "type": "http", "url": "http://127.0.0.1:8765/mcp" }
  }
}
```

提供 10 个工具：`get_game_status`、`list_block_types`、`place_blocks`、
`fill_region`、`fill_regions`、`clear_region`、`get_scene_info`、`save_scene`、
`load_scene`、`reset_world`。

工具函数跑在 uvicorn 的工作线程，而 OpenGL 上下文绑在主线程，所以所有改动都
先排队，由主循环每帧取出执行。

**TCP，`localhost:8001`**

方向跟直觉相反：**游戏是客户端，主动去连服务端**。实现见 `tcp_agent_plugin.py`。

`scene_server.py` 是配套的测试服务端，会下发一串建造指令：

```bash
# 终端 1：先起服务端
uv run python scene_server.py

# 终端 2：再起游戏，必须加 --default
uv run python main.py --default
```

必须加 `--default`：不加就会载入整个存档，而服务端的清场指令只覆盖
x/z ∈ [-16,15] 这一小块，城堡会盖在旧地形上。

## 场景存储格式

格式定义见 `mapv1.md`，编解码实现在 `scene_format.py`。

要点是把世界切成 16×16×16 的 section，每段用局部调色板加游程编码写进 JSON：

```json
{
  "format": "pymc_scene",
  "version": 1,
  "section_size": 16,
  "order": "yzx",
  "block_defs": "mapconfig/blocks.json",
  "used_block_ids": [1, 2, 3],
  "sections": {
    "0,1,0": { "fill": 1 },
    "-1,0,-1": { "p": [0, 1, 2], "rle": [256, 1, 12, 2, 3828, 0] }
  }
}
```

相比逐个方块写 `[x,y,z,id]`，110 万方块的存档从 15 MB 降到 0.6 MB。

方块的名字、贴图、几何模型不写进场景文件，统一放在 `mapconfig/blocks.json`。
改了 `mapconfig/blocks.mcpy` 之后要重新生成一次：

```bash
uv run python gen_block_defs.py
```

## 目录

```
main.py              入口，窗口与主循环
world.py             世界，chunk 字典与方块读写
chunk.py             16×128×16 的区块，负责网格构建与上传 GPU
subchunk.py          4×4×4 子区块，面剔除在这里
block_type.py        方块蓝图，把贴图绑到几何面上
models/              22 种方块几何模型，纯数据
mapconfig/blocks.mcpy    84 种方块的定义源文件
mapconfig/blocks.json    由 blocks.mcpy 生成的共享方块定义
scene_format.py      场景格式编解码
map_data.py          默认地形生成
save/v1/             新格式场景
camera.py shader.py texture_mgr.py hit.py    渲染与拾取
controller.py        键鼠输入
gui_mgr/             imgui 界面层
mcp_server/          MCP 服务
tcp_agent_plugin.py  TCP 客户端插件
scene_server.py      TCP 测试服务端
```
