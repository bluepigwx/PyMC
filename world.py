import block_type
import chunk
import config
import texture_mgr
import random
import models
import math
import map_data
import logging

logger = logging.getLogger(__name__)

class World:
    def __init__(self):
        self.texture_mgr = texture_mgr.TextureMgr(16, 16, 256)
        self.texture_mgr.init()

        self.block_types = [None] # 0 -- 空气
        self._load_block_type()
        self.texture_mgr.gen_mipmap()

        self.chunks = {}
        self.map_data = map_data.MapData(self)
        
    
    def load_map(self):
        logger.info(f"begin load map data...")
        #self.map_data.load()
        self.map_data.build_custom_chunks()
        logger.info(f"end load map data...")
        
        #也可以自定义生成地图
        #self._build_custom_chunks()
        
        logger.info(f"begin build meshs...")
        self.build_meshs()
        logger.info(f"end build meshs...")
        

        
    def _load_block_type(self):
        # parse block type data file
        blocks_data_file = open("data/blocks.mcpy")
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
                self.block_types.append(_block_type)


    def _build_custom_chunks(self):
        for x in range(2):
            for z in range(2):
                chunk_position = (x - 1, -1, z - 1)

                new_chunk = chunk.Chunk(self, chunk_position)

                for i in range(config.CHUNK_WIDHT):
                    for j in range(config.CHUNK_HEIGHT):
                        for k in range(config.CHUNK_LENGHTH):
                            if j == 15:
                                new_chunk.blocks[i][j][k] = random.choices([0, 9, 10], [20, 2, 1])[0]
                            elif j == 14:
                                new_chunk.blocks[i][j][k] =2
                            elif j >10:
                                new_chunk.blocks[i][j][k] = 4
                            else:
                                new_chunk.blocks[i][j][k] = 5

                self.chunks[chunk_position] = new_chunk

        
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
    
    
    def set_block(self, wposition, block_num):
        """
        外部修改block的接口
        """
        logger.debug(f"wposition : {wposition} block_num : {block_num}")
        wx, wy, wz = wposition
        
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










