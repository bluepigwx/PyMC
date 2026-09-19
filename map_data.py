import chunk
import config
import logging
import math

logger = logging.getLogger(__name__)


class MapData:
    """
    负责默认地形生成与批量写入。

    场景的存取不在这里，走 scene_format 模块（单个 JSON 文件，
    路径见 world.DEFAULT_SCENE_PATH）。
    """
    def __init__(self, world):
        self.world = world


    def build_custom_chunks_v2(self):
        """生成围绕世界原点的 4 个 chunk，y=0 铺一层草地。"""
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
        # 丢弃前先释放 GL 缓冲，否则句柄在驱动侧泄漏
        for c in self.world.chunks.values():
            c.dispose()
        self.world.chunks = {}
        self.build_custom_chunks_v2()


    def _put_block_raw(self, wposition, block_id):
        """直接写入方块数据，不做逐块的网格更新。

        调用方需要自己在批量写完后调 world.build_meshs()。
        """
        # 同 world.set_block：非法 id 写进去会让后面的 build_meshs 永久崩溃
        block_id = self.world.validate_block_id(block_id)

        wposition = (math.floor(wposition[0]), math.floor(wposition[1]), math.floor(wposition[2]))

        chunk_position = self.world.get_chunk_position(wposition)
        if chunk_position not in self.world.chunks:
            if block_id == 0:
                return
            self.world.chunks[chunk_position] = chunk.Chunk(self.world, chunk_position)

        bx, by, bz = self.world.get_block_pos_in_chunk(wposition)
        self.world.chunks[chunk_position].blocks[bx][by][bz] = block_id
