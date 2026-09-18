import nbtlib as nb
import chunk
import config
import base36
import logging
import copy
import json
import os
import time

logger = logging.getLogger(__name__)

JSON_FORMAT = "pymc_scene"
JSON_VERSION = 1


class MapData:
    """
    负责场景数据的加载与保存，为了保证地图数据巨大时不因为修改一个字节而存储整个文件，地图数据按照chunk划分到不同的磁盘文件
    """
    def __init__(self, world, path="save"):
        self.world = world
        self.path = path
        self.original_chunks = {}
        
        
    def load(self, path=""):
        for x in range(-4, 4):
            for z in range(-4, 4):
                self._load_chunk((x, 0, z))
                
        
    def build_custom_chunks(self):
        position = (0,0,0)
        new_chunk = chunk.Chunk(self.world, position)
        self.world.chunks[position] = new_chunk
        
        for x in range(config.CHUNK_WIDHT):
            for z in range(config.CHUNK_LENGHTH):
                new_chunk.blocks[x][0][z] = 2

    def build_custom_chunks_v2(self):
        # Generate 4 chunks centered around world origin (0,0,0) at their intersection
        chunk_positions = [
            (-1, 0, -1),
            (-1, 0,  0),
            ( 0, 0, -1),
            ( 0, 0,  0),
        ]
        for position in chunk_positions:
            new_chunk = chunk.Chunk(self.world, position)
            self.world.chunks[position] = new_chunk
            for x in range(config.CHUNK_WIDHT):
                for z in range(config.CHUNK_LENGHTH):
                    new_chunk.blocks[x][0][z] = 2

        
    def reset_map_data(self):
        self.world.chunks = {}
        self.build_custom_chunks_v2()
    
    
    def save(self, path=""):
        pass

    # ------------------------------------------------------------------
    # JSON 场景导出 / 导入
    # ------------------------------------------------------------------
    #
    # 文件结构（format="pymc_scene", version=1）：
    #
    # {
    #   "format": "pymc_scene",
    #   "version": 1,
    #   "generator": "PyMC",
    #   "saved_at": "2026-09-18 17:30:00",
    #   "coordinate_system": {
    #       "axes": "right-handed, +X east, +Y up, +Z south",
    #       "unit": "1 block = 1 unit cube",
    #       "block_origin": "integer world coordinate of the block's min corner"
    #   },
    #   "bounds": {"min": [x,y,z], "max": [x,y,z], "size": [w,h,l]},
    #   "block_count": 2027,
    #   "palette": {
    #       "45": {
    #           "id": 45,
    #           "name": "Bricks",
    #           "model": "models.cube",     # 几何形状，非立方体的如 models.plant/models.slab
    #           "is_cube": true,            # 是否满格立方体
    #           "transparent": false,       # 是否透明（影响相邻面剔除）
    #           "glass": false,
    #           "textures": {"all": "bricks"}   # 面 -> 贴图名，对应 textures/<名>.png
    #       }
    #   },
    #   "encoding": "xyz_id",
    #   "blocks": [[x, y, z, id], ...]      # 只含非空气方块，id 是 palette 的键
    # }
    #
    # 其他程序还原方法：遍历 blocks，取 id 去 palette 查 name/model/textures，
    # 贴图文件在项目 textures/ 目录下，文件名即 textures 里的值加 .png。
    # air 恒为 id 0，不会出现在 blocks 中。

    def _build_palette(self, used_ids):
        """为用到的方块 id 生成类型说明表。"""
        palette = {}
        for block_id in sorted(used_ids):
            entry = {
                "id": block_id,
                "name": "Unknown",
                "model": "models.cube",
                "is_cube": True,
                "transparent": False,
                "glass": False,
                "textures": {},
            }

            if 0 <= block_id < len(self.world.block_types):
                bt = self.world.block_types[block_id]
                if bt is not None:
                    entry["name"] = bt.name
                    entry["is_cube"] = bool(bt.is_cube)
                    entry["transparent"] = bool(bt.transparent)
                    entry["glass"] = bool(bt.glass)
                    entry["textures"] = dict(bt.block_face_textures)
                    model_name = getattr(bt.model, "__name__", None)
                    if model_name:
                        entry["model"] = model_name
                else:
                    logger.warning(f"block id {block_id} has no block type")
            else:
                logger.warning(f"block id {block_id} out of block_types range")

            palette[str(block_id)] = entry

        return palette

    def save_json(self, path="scene.json"):
        """把当前世界里所有非空气方块导出为 JSON 文件。

        Args:
            path: 输出文件路径。

        Returns:
            (block_count, path)
        """
        blocks = []
        used_ids = set()

        min_xyz = [None, None, None]
        max_xyz = [None, None, None]

        for chunk_position, cur_chunk in self.world.chunks.items():
            off_x = chunk_position[0] * config.CHUNK_WIDHT
            off_y = chunk_position[1] * config.CHUNK_HEIGHT
            off_z = chunk_position[2] * config.CHUNK_LENGHTH

            for x in range(config.CHUNK_WIDHT):
                for y in range(config.CHUNK_HEIGHT):
                    for z in range(config.CHUNK_LENGHTH):
                        block_id = cur_chunk.blocks[x][y][z]
                        if block_id == 0:
                            continue

                        wx = off_x + x
                        wy = off_y + y
                        wz = off_z + z

                        blocks.append([wx, wy, wz, int(block_id)])
                        used_ids.add(int(block_id))

                        for i, v in enumerate((wx, wy, wz)):
                            if min_xyz[i] is None or v < min_xyz[i]:
                                min_xyz[i] = v
                            if max_xyz[i] is None or v > max_xyz[i]:
                                max_xyz[i] = v

        if not blocks:
            min_xyz = [0, 0, 0]
            max_xyz = [0, 0, 0]

        size = [max_xyz[i] - min_xyz[i] + 1 for i in range(3)]

        scene = {
            "format": JSON_FORMAT,
            "version": JSON_VERSION,
            "generator": "PyMC",
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "coordinate_system": {
                "axes": "right-handed, +X east, +Y up, +Z south",
                "unit": "1 block = 1 unit cube",
                "block_origin": "integer world coordinate of the block's min corner",
            },
            "bounds": {"min": min_xyz, "max": max_xyz, "size": size},
            "block_count": len(blocks),
            "palette": self._build_palette(used_ids),
            "encoding": "xyz_id",
            "blocks": blocks,
        }

        dir_name = os.path.dirname(os.path.abspath(path))
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(scene, f, ensure_ascii=False, indent=1)

        logger.info(f"save_json: {len(blocks)} blocks -> {path}")
        return len(blocks), path

    def load_json(self, path="scene.json", clear=True):
        """从 JSON 文件还原场景。

        Args:
            path: 输入文件路径。
            clear: True 时先清空当前世界的所有 chunk。

        Returns:
            写入的方块数量。
        """
        with open(path, "r", encoding="utf-8") as f:
            scene = json.load(f)

        fmt = scene.get("format")
        if fmt != JSON_FORMAT:
            raise ValueError(f"unexpected format: {fmt}, expect {JSON_FORMAT}")

        version = scene.get("version")
        if version != JSON_VERSION:
            logger.warning(f"scene version {version} != {JSON_VERSION}, try loading anyway")

        encoding = scene.get("encoding", "xyz_id")
        if encoding != "xyz_id":
            raise ValueError(f"unsupported encoding: {encoding}")

        if clear:
            self.world.chunks = {}

        count = 0
        for item in scene.get("blocks", []):
            wx, wy, wz, block_id = item[0], item[1], item[2], item[3]
            self._put_block_raw((int(wx), int(wy), int(wz)), int(block_id))
            count += 1

        self.world.build_meshs()

        logger.info(f"load_json: {count} blocks <- {path}")
        return count

    def _put_block_raw(self, wposition, block_id):
        """直接写入方块数据，不做逐块的网格更新（批量导入用）。"""
        chunk_position = self.world.get_chunk_position(wposition)
        if chunk_position not in self.world.chunks:
            if block_id == 0:
                return
            self.world.chunks[chunk_position] = chunk.Chunk(self.world, chunk_position)

        bx, by, bz = self.world.get_block_pos_in_chunk(wposition)
        self.world.chunks[chunk_position].blocks[bx][by][bz] = block_id
    
    
    def _load_chunk(self, chunk_position):
        chunk_path = self._chunk_position_to_path(chunk_position)
        with nb.load(chunk_path) as chunk_file:
            chunk_blocks = chunk_file["Level"]["Blocks"]
    
            self.world.chunks[chunk_position] = chunk.Chunk(self.world, chunk_position)
            new_chunk = self.world.chunks[chunk_position]
            #填充数据
            for x in range(config.CHUNK_WIDHT):
                for y in range(config.CHUNK_HEIGHT):
                    for z in range(config.CHUNK_LENGHTH):
                        index = x * config.CHUNK_LENGHTH * config.CHUNK_HEIGHT + z * config.CHUNK_HEIGHT + y
                        if index < len(chunk_blocks):
                            new_chunk.blocks[x][y][z] = chunk_blocks[index]
                        else:
                            logger.error(f"chunk_blocks index out of range: {index}, max: {len(chunk_blocks)}, x={x}, y={y}, z={z}")
                            break
    
    
    def _chunk_position_to_path(self, chunk_position):
        x, y, z = chunk_position
        chunk_path = "/".join(
			(self.path, base36.dumps(x % 64), base36.dumps(z % 64), f"c.{base36.dumps(x)}.{base36.dumps(z)}.dat")
		)
        return chunk_path