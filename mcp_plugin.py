"""游戏内 MCP 服务：跟 main.py 同一个进程，随游戏启动、随游戏退出。

为什么要有主线程队列
--------------------
FastMCP 的工具函数跑在 uvicorn 的工作线程里，而 `world.set_block()` 最终会调
`glBufferData` 上传顶点。OpenGL 上下文绑在 pygame 的主线程上，别的线程调 GL 函数
要么无效果要么直接崩。所以工具函数不自己动 world，而是：

    1. 把一个闭包 append 进 self._jobs（加锁），带一个 threading.Event
    2. 阻塞在 event.wait(timeout) 上
    3. 主线程每帧调 update()，popleft 取出闭包执行，把返回值写进 job.result，
       再 event.set() 唤醒工具函数
    4. 工具函数读 job.result 返回给 Agent

传输只能用 HTTP（默认 127.0.0.1:8765/mcp）。stdio 那种要求 MCP 客户端自己拉起
进程，跟"服务住在游戏进程里"矛盾。

Agent 侧配置：
    {"mcpServers": {"pymc": {"type": "http", "url": "http://127.0.0.1:8765/mcp"}}}

环境变量：
    PYMC_MCP_HOST      默认 127.0.0.1
    PYMC_MCP_PORT      默认 8765
    PYMC_JOB_TIMEOUT   等主线程执行完的超时秒数，默认 120
    PYMC_MAX_BLOCKS    单次调用方块数上限，默认 200000
"""

from __future__ import annotations

import logging
import os
import re
import threading
from collections import Counter, deque
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

logger = logging.getLogger(__name__)

MCP_HOST = os.environ.get("PYMC_MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.environ.get("PYMC_MCP_PORT", "8765"))
JOB_TIMEOUT = float(os.environ.get("PYMC_JOB_TIMEOUT", "120"))
MAX_BLOCKS = int(os.environ.get("PYMC_MAX_BLOCKS", "200000"))

# 超过这么多方块就改用「先写数据、最后统一重建全部网格」的路径
BULK_THRESHOLD = 256

PROJECT_DIR = Path(__file__).resolve().parent


# ----------------------------------------------------------------------
# 方块类型表
# ----------------------------------------------------------------------

_ID_RE = re.compile(r"^\s*(\d+)\s*:(.*)$")
_NAME_RE = re.compile(r'name\s+"([^"]*)"')
_SAMEAS_RE = re.compile(r"sameas\s+(\d+)")
_MODEL_RE = re.compile(r"model\s+models\.(\w+)")


def _load_block_types():
    """从 data/blocks.mcpy 读出 {id: {"name":..., "model":...}}，只用于给 Agent 看。"""
    table = {0: {"name": "Air", "model": "-"}}
    path = PROJECT_DIR / "data" / "blocks.mcpy"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        logger.error(f"cannot read {path}: {e}")
        return table

    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _ID_RE.match(line)
        if not m:
            continue

        block_id = int(m.group(1))
        props = m.group(2)

        name, model = "Unknown", "cube"
        sameas = _SAMEAS_RE.search(props)
        if sameas:
            base = table.get(int(sameas.group(1)))
            if base:
                name, model = base["name"], base["model"]
        name_m = _NAME_RE.search(props)
        if name_m:
            name = name_m.group(1)
        model_m = _MODEL_RE.search(props)
        if model_m:
            model = model_m.group(1)

        table[block_id] = {"name": name, "model": model}
    return table


BLOCK_TYPES = _load_block_types()


# ----------------------------------------------------------------------
# 参数模型
# ----------------------------------------------------------------------


class BlockSpec(BaseModel):
    """一个方块。type=0 是空气，即删除该坐标的方块。"""

    x: int = Field(description="world X (east+)")
    y: int = Field(description="world Y (up+); y=0 is the pre-generated grass ground, build from y=1")
    z: int = Field(description="world Z (south+)")
    type: int = Field(description="block type id 0..84; 0 = air = remove")


class Coord(BaseModel):
    x: int
    y: int
    z: int


class CoordType(Coord):
    type: int = Field(description="block type id used here instead of the region default")


class Region(BaseModel):
    """一个轴对齐长方体，边界闭区间。可以挖洞(exclude)、可以局部换材质(override)。"""

    type: int = Field(description="default block type id filling the box; 0 = clear")
    x_min: int
    x_max: int
    y_min: int
    y_max: int
    z_min: int
    z_max: int
    exclude: list[Coord] = Field(default_factory=list, description="coords to skip: door/window holes")
    override: list[CoordType] = Field(default_factory=list, description="coords filled with another type")

    def validate_bounds(self) -> None:
        if self.x_min > self.x_max or self.y_min > self.y_max or self.z_min > self.z_max:
            raise ToolError(
                f"invalid bounds: x[{self.x_min},{self.x_max}] y[{self.y_min},{self.y_max}] "
                f"z[{self.z_min},{self.z_max}] (min must be <= max)"
            )

    def volume(self) -> int:
        return (
            (self.x_max - self.x_min + 1)
            * (self.y_max - self.y_min + 1)
            * (self.z_max - self.z_min + 1)
        )

    def expand(self):
        """展开成 [(type, x, y, z), ...]，逻辑与 tcp_agent_plugin._expand_regions 一致。"""
        exclude_set = {(c.x, c.y, c.z) for c in self.exclude}
        override_map = {(c.x, c.y, c.z): c.type for c in self.override}

        blocks = []
        for y in range(self.y_min, self.y_max + 1):
            for x in range(self.x_min, self.x_max + 1):
                for z in range(self.z_min, self.z_max + 1):
                    if (x, y, z) in exclude_set:
                        continue
                    blocks.append((override_map.get((x, y, z), self.type), x, y, z))
        return blocks


def _check_type_ids(ids) -> None:
    bad = sorted({i for i in ids if i not in BLOCK_TYPES})
    if bad:
        raise ToolError(f"unknown block type id(s): {bad}. Call list_block_types for valid ids.")


def _check_volume(total: int) -> None:
    if total > MAX_BLOCKS:
        raise ToolError(
            f"request would write {total} blocks, over the {MAX_BLOCKS} limit. "
            "Split it up or raise PYMC_MAX_BLOCKS."
        )


# ----------------------------------------------------------------------
# 主线程任务槽
# ----------------------------------------------------------------------


class _Job:
    __slots__ = ("fn", "event", "result", "error", "cancelled")

    def __init__(self, fn: Callable[[], Any]) -> None:
        self.fn = fn
        self.event = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None
        # 工具函数等超时后置位。主线程取出 job 时先看这个标志，
        # 否则调用方已经收到 timeout 报错了，方块过一会儿又被建出来，
        # Agent 重试就会建两遍。
        self.cancelled = False


# ----------------------------------------------------------------------
# 插件
# ----------------------------------------------------------------------


class Plugin:
    """挂在 Application 上的 MCP 插件，接口跟 tcp_agent_plugin.Plugin 对齐。"""

    def __init__(self, world, controller, host: str = MCP_HOST, port: int = MCP_PORT):
        self.world = world
        self.controller = controller
        self.enable = True

        self._host = host
        self._port = port

        self._jobs: deque[_Job] = deque()
        self._process_jobs: deque[_Job] = deque()
        self._lock = threading.Lock()

        self._thread: threading.Thread | None = None
        self._server_ready = threading.Event()
        self._stopping = False

        self._stats = {"tool_calls": 0, "blocks_written": 0}

        self.mcp = self._build_server()

    # -- 生命周期 ------------------------------------------------------

    def init(self):
        """起一个守护线程跑 HTTP MCP 服务。守护线程随进程退出，不会挡住游戏关闭。"""
        if not self.enable:
            return

        self._thread = threading.Thread(target=self._serve, name="mcp-http", daemon=True)
        self._thread.start()
        logger.info(f"mcp server thread started, http://{self._host}:{self._port}/mcp")

    def _serve(self):
        try:
            self._server_ready.set()
            self.mcp.run(transport="http", host=self._host, port=self._port, show_banner=False)
        except Exception as e:
            logger.error(f"mcp server stopped: {e}")
        finally:
            logger.info("mcp server thread exiting")

    def finit(self):
        """游戏退出时调用：把还在等的工具调用唤醒，别让 HTTP 请求吊死。"""
        self._stopping = True
        with self._lock:
            pending = list(self._jobs) + list(self._process_jobs)
            self._jobs.clear()
            self._process_jobs.clear()
        for job in pending:
            job.error = RuntimeError("game is shutting down")
            job.event.set()
        logger.info(f"mcp plugin finit, dropped {len(pending)} pending job(s)")

    # -- 主线程 --------------------------------------------------------

    def update(self):
        """每帧在主线程调用：排空任务队列并执行。交换队列把临界区压到最小。"""
        if not self.enable:
            return

        with self._lock:
            self._jobs, self._process_jobs = self._process_jobs, self._jobs

        while self._process_jobs:
            job = self._process_jobs.popleft()
            if job.cancelled:
                logger.warning("skipping cancelled mcp job (caller already timed out)")
                continue
            try:
                job.result = job.fn()
            except BaseException as e:  # noqa: BLE001 - 必须捕获，否则工具端永远等下去
                logger.error(f"mcp job failed: {e}")
                job.error = e
            finally:
                job.event.set()

    # -- 工具线程 ------------------------------------------------------

    def _run_on_main(self, fn: Callable[[], Any]) -> Any:
        """在主线程执行 fn 并把结果带回来。工具函数全部走这里。"""
        if self._stopping:
            raise ToolError("game is shutting down")

        job = _Job(fn)
        with self._lock:
            self._jobs.append(job)

        if not job.event.wait(JOB_TIMEOUT):
            job.cancelled = True
            raise ToolError(
                f"timed out after {JOB_TIMEOUT}s waiting for the game's render thread. "
                "The window may be frozen or being dragged; nothing was written."
            )

        if job.error is not None:
            raise ToolError(f"game raised: {job.error}")
        return job.result

    # -- 落到 world 的实际写入 ----------------------------------------

    def _write_blocks(self, blocks) -> int:
        """blocks 是 [(type, x, y, z), ...]，必须在主线程调用。

        少量方块逐个走 world.set_block（它自己会刷新所在 chunk 及邻居的网格）。
        量大时改走 map_data._put_block_raw 只写 blocks 数组，最后一次
        world.build_meshs() 统一重建——省掉每块一次 glBufferData。
        """
        if len(blocks) < BULK_THRESHOLD:
            for block_type, x, y, z in blocks:
                self.world.set_block((x, y, z), block_type)
        else:
            put_raw = self.world.map_data._put_block_raw
            for block_type, x, y, z in blocks:
                put_raw((x, y, z), block_type)
            self.world.build_meshs()

        self._stats["blocks_written"] += len(blocks)
        return len(blocks)

    def _fill_regions(self, regions: list[Region]) -> dict:
        if not regions:
            raise ToolError("regions is empty")

        type_ids, total = [], 0
        for r in regions:
            r.validate_bounds()
            type_ids.append(r.type)
            type_ids.extend(o.type for o in r.override)
            total += r.volume()
        _check_type_ids(type_ids)
        _check_volume(total)

        blocks = []
        for r in regions:
            blocks.extend(r.expand())

        written = self._run_on_main(lambda: self._write_blocks(blocks))
        return {"placed": written, "regions": len(regions)}

    # -- 工具注册 ------------------------------------------------------

    def _build_server(self) -> FastMCP:
        mcp = FastMCP(
            name="pymc",
            version="0.1.0",
            instructions=(
                "Build inside a running PyMC voxel world (a Minecraft-like renderer). "
                "This server lives in the game process: if calls fail with connection errors, "
                "the game window is closed.\n"
                "Integer world coordinates, +X east, +Y up, +Z south. y=0 is the pre-generated "
                "grass ground over x/z in [-16,15], so build upward from y=1. Block type ids are "
                "0..84 (0 = air = remove); call list_block_types if unsure.\n"
                "Prefer fill_regions over place_blocks for box shapes: it is one call and the "
                "game batches the mesh rebuild."
            ),
        )

        @mcp.tool
        def get_game_status() -> dict:
            """Check that the game is alive and responding, plus current limits and counters."""
            self._stats["tool_calls"] += 1
            camera = self._run_on_main(lambda: {
                "pos": [round(v, 2) for v in self.controller._position],
                "forward": [round(v, 2) for v in self.controller._forward],
            })
            return {
                "game_running": True,
                "mcp_endpoint": f"http://{self._host}:{self._port}/mcp",
                "camera": camera,
                "chunks_loaded": len(self.world.chunks),
                "job_timeout_sec": JOB_TIMEOUT,
                "max_blocks_per_call": MAX_BLOCKS,
                "tool_calls": self._stats["tool_calls"],
                "blocks_written": self._stats["blocks_written"],
            }

        @mcp.tool
        def list_block_types() -> dict:
            """List every usable block type id with its name and geometry model.

            `model` matters when building: only `cube` blocks are full opaque cubes.
            `plant`, `torch`, `slab`, `stairs`, `flat` are partial shapes;
            `glass`, `leaves`, `liquid` are see-through.
            """
            return {
                "count": len(BLOCK_TYPES),
                "note": "id 0 is air; writing 0 removes a block",
                "blocks": [
                    {"id": bid, "name": info["name"], "model": info["model"]}
                    for bid, info in sorted(BLOCK_TYPES.items())
                ],
            }

        @mcp.tool
        def place_blocks(blocks: list[BlockSpec]) -> dict:
            """Set individual blocks at explicit coordinates. Use for scattered shapes.

            For boxes use fill_region / fill_regions instead.
            """
            self._stats["tool_calls"] += 1
            if not blocks:
                raise ToolError("blocks is empty")
            _check_type_ids([b.type for b in blocks])
            _check_volume(len(blocks))

            payload = [(b.type, b.x, b.y, b.z) for b in blocks]
            written = self._run_on_main(lambda: self._write_blocks(payload))
            return {"placed": written}

        @mcp.tool
        def fill_region(
            type: int,
            x_min: int,
            x_max: int,
            y_min: int,
            y_max: int,
            z_min: int,
            z_max: int,
            exclude: list[Coord] | None = None,
            override: list[CoordType] | None = None,
        ) -> dict:
            """Fill one axis-aligned box (bounds inclusive) with a block type.

            `exclude` skips coordinates (door holes, battlement gaps). `override` swaps
            single coordinates to another type (glass panes in a brick wall). type=0 clears.
            """
            self._stats["tool_calls"] += 1
            region = Region(
                type=type,
                x_min=x_min, x_max=x_max,
                y_min=y_min, y_max=y_max,
                z_min=z_min, z_max=z_max,
                exclude=exclude or [],
                override=override or [],
            )
            return self._fill_regions([region])

        @mcp.tool
        def fill_regions(regions: list[Region]) -> dict:
            """Fill many boxes in one call — the main building tool.

            A house is just a list of boxes: floor, four walls with door holes excluded and
            glass overridden, roof layers. Sending them together means one mesh rebuild.
            """
            self._stats["tool_calls"] += 1
            return self._fill_regions(regions)

        @mcp.tool
        def clear_region(
            x_min: int = -16,
            x_max: int = 15,
            y_min: int = 1,
            y_max: int = 14,
            z_min: int = -16,
            z_max: int = 15,
        ) -> dict:
            """Delete every block in a box. Defaults wipe the build area above the ground,
            keeping the y=0 grass plane."""
            self._stats["tool_calls"] += 1
            return self._fill_regions([Region(
                type=0,
                x_min=x_min, x_max=x_max,
                y_min=y_min, y_max=y_max,
                z_min=z_min, z_max=z_max,
            )])

        @mcp.tool
        def get_scene_info(include_blocks: bool = False, max_blocks: int = 300) -> dict:
            """Read the world back: camera pose, per-type block counts, bounding box.

            The world holds thousands of blocks, so the full list is omitted by default.
            include_blocks=True returns up to max_blocks entries.
            """
            self._stats["tool_calls"] += 1

            def job():
                return {
                    "camera": {
                        "pos": [round(v, 2) for v in self.controller._position],
                        "forward": [round(v, 2) for v in self.controller._forward],
                        "up": [round(v, 2) for v in self.controller._up],
                        "right": [round(v, 2) for v in self.controller._right],
                    },
                    "blocks": self.world.get_all_blocks(),
                }

            scene = self._run_on_main(job)
            blocks = scene["blocks"]

            counts = Counter(b["type"] for b in blocks)
            bounds = None
            if blocks:
                xs = [b["pos"][0] for b in blocks]
                ys = [b["pos"][1] for b in blocks]
                zs = [b["pos"][2] for b in blocks]
                bounds = {"min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]}

            info = {
                "camera": scene["camera"],
                "block_count": len(blocks),
                "bounds": bounds,
                "by_type": [
                    {"id": bid, "name": BLOCK_TYPES.get(bid, {}).get("name", "Unknown"), "count": n}
                    for bid, n in counts.most_common()
                ],
            }
            if include_blocks:
                info["blocks"] = blocks[:max_blocks]
                info["blocks_truncated"] = len(blocks) > max_blocks
            return info

        @mcp.tool
        def save_scene(path: str = "scene.json") -> dict:
            """Save the world to a JSON file, relative to the game's working directory."""
            self._stats["tool_calls"] += 1
            count, saved = self._run_on_main(lambda: self.world.save_scene_json(path))
            return {"path": saved, "block_count": count}

        @mcp.tool
        def load_scene(path: str = "scene.json", clear: bool = True) -> dict:
            """Load a world from a save_scene JSON file. clear=True wipes the world first."""
            self._stats["tool_calls"] += 1
            count = self._run_on_main(lambda: self.world.load_scene_json(path, clear))
            return {"path": path, "block_count": count}

        @mcp.tool
        def reset_world() -> dict:
            """Wipe everything and regenerate the flat grass ground (same as pressing R in-game)."""
            self._stats["tool_calls"] += 1
            self._run_on_main(self.world.reset_map)
            return {"status": "reset", "chunks_loaded": len(self.world.chunks)}

        return mcp

    # -- 给 ChatBox 用的空实现（保持与 tcp_agent_plugin 接口一致）------

    def set_chat_callback(self, callback):
        pass

    def set_chat_stream_callbacks(self, on_start, on_delta, on_end):
        pass

    def send_chat(self, text):
        logger.info(f"mcp plugin has no chat channel, ignoring: {text[:80]}")
