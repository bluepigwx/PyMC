import block_type
import chunk
import config
import texture_mgr
import models
import math
import map_data
import scene_serializer
import logging

logger = logging.getLogger(__name__)

DEFAULT_SCENE_PATH = "save/v1/world.json"

# 超过这么多方块就改用「先写数据、最后统一重建全部网格」的路径
BULK_THRESHOLD = 256

class World:
    def __init__(self):
        self.texture_mgr = texture_mgr.TextureMgr(16, 16, 256)
        self.texture_mgr.init()

        self.block_types = [None] # 0 -- 空气
        self._load_block_type()
        self.texture_mgr.gen_mipmap()

        self.chunks = {}
        self.map_data = map_data.MapData(self)
        
    
    def load_map(self, path=None):
        """载入地图。

        给了 path 就从场景文件读，没给就生成默认的 4 块草地。
        """
        if path:
            logger.info(f"begin load scene {path} ...")
            count = self.load_scene_json(path)
            logger.info(f"end load scene, {count} blocks in {len(self.chunks)} chunks")
            return count

        logger.info(f"begin load map data...")
        self.map_data.build_custom_chunks_v2()
        logger.info(f"end load map data...")

        logger.info(f"begin build meshs...")
        self.build_meshs()
        logger.info(f"end build meshs...")
        return None
        
        
    def reset_map(self):
        logger.info(f"reset map")
        
        self.map_data.reset_map_data()
        self.build_meshs()


    def save_scene_json(self, path=DEFAULT_SCENE_PATH):
        """把当前场景导出为 JSON 文件，返回 (方块数, 路径)。

        格式见 mapv1.md：section + 局部调色板 + 游程编码。
        方块类型说明不写进来，在 mapconfig/blocks.json 里。
        """
        return scene_serializer.save_world(self, path)


    def load_scene_json(self, path=DEFAULT_SCENE_PATH, clear=True):
        """从 JSON 文件加载场景，返回方块数。"""
        return scene_serializer.load_world(self, path, clear)
        

        
    def _load_block_type(self):
        # parse block type data file
        blocks_data_file = open("mapconfig/blocks.mcpy")
        blocks_data = blocks_data_file.readlines()
        blocks_data_file.close()

        for block in blocks_data:
            if block[0] in ["\n", "#"]:  # skip if empty line or comment
                continue

            number, props = block.split(":", 1)
            number = int(number)

			# default block
            name = "Unknown"
            model = models.cube
            texture = {"all": "unknown"}

			# read properties
            for prop in props.split(","):
                prop = prop.strip()
                prop = list(filter(None, prop.split(" ", 1)))

                if prop[0] == "sameas":
                    sameas_number = int(prop[1])
                    name = self.block_types[sameas_number].name
                    texture = dict(self.block_types[sameas_number].block_face_textures)
                    model = self.block_types[sameas_number].model
                elif prop[0] == "name":
                    name = eval(prop[1])
                elif prop[0][:7] == "texture":
                    _, side = prop[0].split(".")
                    texture[side] = prop[1].strip()
                elif prop[0] == "model":
                    model = eval(prop[1])

			# add block type
            _block_type = block_type.BlockType(self.texture_mgr, name, texture, model)
            if number < len(self.block_types):
                self.block_types[number] = _block_type
            else:
                # blocks.mcpy 中间缺 id 时用 None 补齐，否则后续 id 全部错位
                while len(self.block_types) < number:
                    self.block_types.append(None)
                self.block_types.append(_block_type)


    def build_meshs(self):
        for _, c in self.chunks.items():
            c.update_subchunk_mesh()
            c.update_mesh()


    def get_block_number(self, x, y, z):
        """
        获得指定世界坐标的方块类型
        """
        cx = x // config.CHUNK_WIDHT
        cy = y // config.CHUNK_HEIGHT
        cz = z // config.CHUNK_LENGHTH

        bx = x % config.CHUNK_WIDHT
        by = y % config.CHUNK_HEIGHT
        bz = z % config.CHUNK_LENGHTH

        # 检查 chunk 是否存在，如果不存在返回 0（空气）
        chunk_pos = (cx, cy, cz)
        if chunk_pos not in self.chunks:
            return 0
        
        cur_chunk = self.chunks[chunk_pos]
        return cur_chunk.blocks[bx][by][bz]
    
    
    def get_chunk_position(self, wposition):
        """
        世界坐标到chunk之间的转换
        """
        wx, wy, wz = wposition
        return (
            math.floor(wx / config.CHUNK_WIDHT),
            math.floor(wy / config.CHUNK_HEIGHT),
            math.floor(wz / config.CHUNK_LENGHTH)
        )
        
        
    def get_block_pos_in_chunk(self, wpostion):
        """
        获得block在自己所在chunk中的相对位置
        """
        wx, wy, wz = wpostion
        return (
            int(wx % config.CHUNK_WIDHT),
            int(wy % config.CHUNK_HEIGHT),
            int(wz % config.CHUNK_LENGHTH)
        )
        
    
    def is_opaque_block(self, wposition):
        """
        指定世界坐标的block是否为不透明体
        """
        wx, wy, wz = wposition
        block_num = self.get_block_number(wx, wy, wz)
        
        block_type = self.block_types[block_num]
        if not block_type:
            return False
        
        return not block_type.transparent
    
    
    def get_all_blocks(self):
        """
        以世界坐标返回所有的block信息
        """
        blocks = []
        
        try:
            for k, v in self.chunks.items():
                c_offset_x = k[0] * config.CHUNK_WIDHT
                c_offset_y = k[1] * config.CHUNK_HEIGHT
                c_offset_z = k[2] * config.CHUNK_LENGHTH
            
                for x in range(config.CHUNK_WIDHT):
                    for y in range(config.CHUNK_HEIGHT):
                        for z in range(config.CHUNK_LENGHTH):
                            block_type = v.blocks[x][y][z]
                            if block_type == 0:
                                continue
                            
                            w_x = c_offset_x + x
                            w_y = c_offset_y + y
                            w_z = c_offset_z + z
                        
                            block_info = {"type":block_type, "pos":[w_x, w_y, w_z]}
                            blocks.append(block_info)
                            
        except Exception as e:
            logger.error(f"get_all_blocks {e}")

        return blocks
    
    
    def validate_block_id(self, block_num):
        """校验方块 id 合法性，返回规整后的 int id，非法则抛 ValueError。

        必须在写入前校验。一旦把非法 id 写进 blocks 数组，
        之后每次 update_mesh / build_meshs 取 block_types[id] 都会 IndexError，
        整个世界从此再也重建不了网格。
        """
        block_num = int(block_num)
        if block_num < 0 or block_num >= len(self.block_types):
            raise ValueError(
                f"invalid block id {block_num}, valid range 0..{len(self.block_types) - 1}"
            )
        if block_num != 0 and self.block_types[block_num] is None:
            raise ValueError(f"block id {block_num} is not defined in mapconfig/blocks.mcpy")
        return block_num

    def write_blocks(self, blocks):
        """批量写入 [(type, x, y, z), ...]，返回写入数量。

        少量方块逐个走 set_block（它自己会刷新所在 chunk 及邻居的网格）。
        量大时改走 map_data._put_block_raw 只写 blocks 数组，最后一次
        build_meshs() 统一重建——省掉每块一次 glBufferData。
        """
        if len(blocks) < BULK_THRESHOLD:
            for block_type, x, y, z in blocks:
                self.set_block((x, y, z), block_type)
        else:
            put_raw = self.map_data._put_block_raw
            for block_type, x, y, z in blocks:
                put_raw((x, y, z), block_type)
            self.build_meshs()
        return len(blocks)

    def block_stats(self):
        """统计所有非空气方块，返回 (总数, {id: 数量}, bounds)。

        不构造逐块 dict，供 get_scene_info 这类只读统计用，
        大世界下比 get_all_blocks 省一大块内存。
        """
        counts = {}
        total = 0
        lo = [None, None, None]
        hi = [None, None, None]
        for (cx, cy, cz), c in self.chunks.items():
            ox = cx * config.CHUNK_WIDHT
            oy = cy * config.CHUNK_HEIGHT
            oz = cz * config.CHUNK_LENGHTH
            for x in range(config.CHUNK_WIDHT):
                col = c.blocks[x]
                wx = ox + x
                for y in range(config.CHUNK_HEIGHT):
                    row = col[y]
                    wy = oy + y
                    for z in range(config.CHUNK_LENGHTH):
                        v = row[z]
                        if not v:
                            continue
                        counts[v] = counts.get(v, 0) + 1
                        total += 1
                        wz = oz + z
                        for i, w in enumerate((wx, wy, wz)):
                            if lo[i] is None or w < lo[i]:
                                lo[i] = w
                            if hi[i] is None or w > hi[i]:
                                hi[i] = w
        bounds = {"min": lo, "max": hi} if total else None
        return total, counts, bounds

    def set_block(self, wposition, block_num):
        """
        外部修改block的接口
        """
        logger.debug(f"wposition : {wposition} block_num : {block_num}")

        # 坐标取整：blocks 是三层 python list，浮点下标会 TypeError
        wx = math.floor(wposition[0])
        wy = math.floor(wposition[1])
        wz = math.floor(wposition[2])
        wposition = (wx, wy, wz)

        block_num = self.validate_block_id(block_num)

        chunk_position = self.get_chunk_position(wposition)
        if chunk_position not in self.chunks:
            if block_num == 0:
                return # 在虚空位置删除方块忽略
            
            #创建新的chunk
            self.chunks[chunk_position] = chunk.Chunk(self, chunk_position)
            
        if self.get_block_number(wx, wy, wz) == block_num:
            logger.debug(f"same block return")
            return
        
        blx, bly, blz = self.get_block_pos_in_chunk(wposition)
        self.chunks[chunk_position].blocks[blx][bly][blz] = block_num
        logger.debug(f"finish add block at bx:{blx} by:{bly} bz:{blz} block:{block_num}")
        self.chunks[chunk_position].update_at_position((wx, wy, wz))
        self.chunks[chunk_position].update_mesh()
        
        cx, cy, cz = chunk_position
        # 如果修改到邻居chunk了，那么相邻的chunk也需要作出修改
        def try_update_chunk_at_position(chunk_position, position):
            if chunk_position in self.chunks:
                self.chunks[chunk_position].update_at_position(position)
                self.chunks[chunk_position].update_mesh()

        if blx == config.CHUNK_WIDHT - 1:
            try_update_chunk_at_position((cx + 1, cy, cz), (wx + 1, wy, wz))
        if blx == 0:
            try_update_chunk_at_position((cx - 1, cy, cz), (wx - 1, wy, wz))

        if bly == config.CHUNK_HEIGHT - 1:
            try_update_chunk_at_position((cx, cy + 1, cz), (wx, wy + 1, wz))
        if bly == 0:
            try_update_chunk_at_position((cx, cy - 1, cz), (wx, wy - 1, wz))

        if blz == config.CHUNK_LENGHTH - 1:
            try_update_chunk_at_position((cx, cy, cz + 1), (wx, wy, wz + 1))
        if blz == 0:
            try_update_chunk_at_position((cx, cy, cz - 1), (wx, wy, wz - 1))



    def draw(self):
        for _, c in self.chunks.items():
            c.draw()










