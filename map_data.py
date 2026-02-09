import nbtlib as nb
import chunk
import config
import base36
import logging

logger = logging.getLogger(__name__)


class MapData:
    """
    负责场景数据的加载与保存，为了保证地图数据巨大时不因为修改一个字节而存储整个文件，地图数据按照chunk划分到不同的磁盘文件
    """
    def __init__(self, world, path="save"):
        self.world = world
        self.path = path
        
        
    def load(self, path=""):
        for x in range(-4, 4):
            for z in range(-4, 4):
                self._load_chunk((x, 0, z))
                
        
    def build_custom_chunks(self):
        position = (0,0,0)
        self.world.chunks[position] = chunk.Chunk(self.world, position)
        new_chunk = self.world.chunks[position]
        
        for x in range(config.CHUNK_WIDHT):
            for z in range(config.CHUNK_LENGHTH):
                new_chunk.blocks[x][0][z] = 2
    
    
    def save(self, path=""):
        pass
    
    
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