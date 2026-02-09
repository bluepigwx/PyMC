import config
from OpenGL.GL import *
import numpy as np
import subchunk
import math


class Chunk:
    def __init__(self, world, position):
        self.position = position
        self.world_position_offset = (
            self.position[0] * config.CHUNK_WIDHT,
            self.position[1] * config.CHUNK_HEIGHT,
            self.position[2] * config.CHUNK_LENGHTH
        )

        self._world = world

        self.blocks = [
			[
				[0 for z in range(config.CHUNK_LENGHTH)]  # 初始化为0
				for y in range(config.CHUNK_HEIGHT)
			]
			for x in range(config.CHUNK_WIDHT)
		]

        self._init_raw_data()

        self._vao = glGenVertexArrays(1)
        # 定点缓冲
        self._vertex_vbo = glGenBuffers(1)
        # 纹理缓冲
        self._tex_coord_vbo = glGenBuffers(1)
        # 光照缓冲
        self._shading_vbo = glGenBuffers(1)
        # 索引缓冲
        self._indicat_vbo = glGenBuffers(1)
        # subchunks
        self._subchunks = {} # position -- subchunk
        sub_x = int(config.CHUNK_WIDHT / config.SUBCHUNK_WIDTH)
        sub_y = int(config.CHUNK_HEIGHT / config.SUBCHUNK_HEIGHT)
        sub_z = int(config.CHUNK_LENGHTH / config.SUBCHUNK_LENGTH)
        
        for x in range(sub_x):
            for y in range(sub_y):
                for z in range(sub_z):
                    self._subchunks[(x, y, z)] = subchunk.SubChunk(self._world, self, (x, y, z))


    def _init_raw_data(self):
        self._raw_mesh_vertex_position = []
        self._raw_mesh_tex_coord = []
        self._raw_mesh_shading_value = []

        self._mesh_index_counter = 0
        self._mesh_indicates = []


    def update_mesh(self):

        self._init_raw_data()
        
        for _, subchunk in self._subchunks.items():
            self._raw_mesh_vertex_position.extend(subchunk.mesh_vertex_position)
            self._raw_mesh_tex_coord.extend(subchunk.mesh_tex_coord)
            self._raw_mesh_shading_value.extend(subchunk.mesh_shading_value)
            
            mesh_indices = [index + self._mesh_index_counter for index in subchunk.mesh_indicates]
            
            self._mesh_indicates.extend(mesh_indices)
            self._mesh_index_counter += subchunk.mesh_index_counter
        

        # 啥都没生成出来，是有可能的，例如chunk被四面八方的chunk给包围住了并且不留空隙        
        if len(self._mesh_indicates) == 0:
            return

        # 上传几何数据
        glBindVertexArray(self._vao)
        # local =0 放置顶点缓冲数据
        glBindBuffer(GL_ARRAY_BUFFER, self._vertex_vbo)
        mesh_vertex_position = np.array(self._raw_mesh_vertex_position, np.float32)
        glBufferData(GL_ARRAY_BUFFER, mesh_vertex_position.nbytes, mesh_vertex_position, GL_STATIC_DRAW)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * mesh_vertex_position.dtype.itemsize, None)
        glEnableVertexAttribArray(0)
        # local = 1 放置纹理坐标缓冲
        glBindBuffer(GL_ARRAY_BUFFER, self._tex_coord_vbo)
        tex_coord= np.array(self._raw_mesh_tex_coord, np.float32)
        glBufferData(GL_ARRAY_BUFFER, tex_coord.nbytes, tex_coord, GL_STATIC_DRAW)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 3 * tex_coord.dtype.itemsize, None)
        glEnableVertexAttribArray(1)
        # local =2 放置光照参数
        glBindBuffer(GL_ARRAY_BUFFER, self._shading_vbo)
        shading_value = np.array(self._raw_mesh_shading_value, np.float32)
        glBufferData(GL_ARRAY_BUFFER, shading_value.nbytes, shading_value, GL_STATIC_DRAW)
        glVertexAttribPointer(2, 1, GL_FLOAT, GL_FALSE, 1 * shading_value.dtype.itemsize, None)
        glEnableVertexAttribArray(2)
        # 最后更新缩影
        indecates = np.array(self._mesh_indicates, np.uint32)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._indicat_vbo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indecates.nbytes, indecates, GL_STATIC_DRAW)
        
        
    def update_subchunk_mesh(self):
        for _, subchunk in self._subchunks.items():
            subchunk.update_mesh()
    
    
    def update_at_position(self, position):
        x, y, z = position

        lx = int(x % config.SUBCHUNK_WIDTH)
        ly = int(y % config.SUBCHUNK_HEIGHT)
        lz = int(z % config.SUBCHUNK_LENGTH)

        clx, cly, clz = self._world.get_block_pos_in_chunk(position)

        sx = math.floor(clx / config.SUBCHUNK_WIDTH)
        sy = math.floor(cly / config.SUBCHUNK_HEIGHT)
        sz = math.floor(clz / config.SUBCHUNK_LENGTH)

        self._subchunks[(sx, sy, sz)].update_mesh()

        def try_update_subchunk_mesh(subchunk_position):
            if subchunk_position in self._subchunks:
                self._subchunks[subchunk_position].update_mesh()

        if lx == config.SUBCHUNK_WIDTH - 1:
            try_update_subchunk_mesh((sx + 1, sy, sz))
        if lx == 0:
            try_update_subchunk_mesh((sx - 1, sy, sz))

        if ly == config.SUBCHUNK_HEIGHT - 1:
            try_update_subchunk_mesh((sx, sy + 1, sz))
        if ly == 0:
            try_update_subchunk_mesh((sx, sy - 1, sz))

        if lz == config.SUBCHUNK_LENGTH - 1:
            try_update_subchunk_mesh((sx, sy, sz + 1))
        if lz == 0:
            try_update_subchunk_mesh((sx, sy, sz - 1))

    
    def draw(self):
        if len(self._mesh_indicates) == 0:
            return
        
        #glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
        
        glBindVertexArray(self._vao)
        glDrawElements(GL_TRIANGLES, len(self._mesh_indicates), GL_UNSIGNED_INT, None)
        



