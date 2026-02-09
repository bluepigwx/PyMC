import config


class SubChunk:
    def __init__(self, world, owner_chunk, sub_position):
        self._sub_position = sub_position
        self._owner_chunk = owner_chunk
        self._world = world
        
        self._local_position = (
            self._sub_position[0] * config.SUBCHUNK_WIDTH,
			self._sub_position[1] * config.SUBCHUNK_HEIGHT,
			self._sub_position[2] * config.SUBCHUNK_LENGTH,
        )

        self._position = (
            self._owner_chunk.world_position_offset[0] + self._local_position[0],
			self._owner_chunk.world_position_offset[1] + self._local_position[1],
			self._owner_chunk.world_position_offset[2] + self._local_position[2],
        )
        # 初始化渲染数据
        self._reset_mesh_data()
        

    def _reset_mesh_data(self):
        # 渲染数据
        self.mesh_vertex_position = []
        self.mesh_tex_coord = []
        self.mesh_shading_value = []
        self.mesh_index_counter = 0
        self.mesh_indicates = []


    def update_mesh(self):
        # 重建subchunk的几何数据
        self._reset_mesh_data()
		
        def add_face(face):
            vertex_positions = block_type.vertices[face].copy()
            for i in range(4):
                vertex_positions[i * 3 + 0] += x
                vertex_positions[i * 3 + 1] += y
                vertex_positions[i * 3 + 2] += z

            self.mesh_vertex_position.extend(vertex_positions)

            indices = [0, 1, 2, 0, 2, 3]
            for i in range(6):
                indices[i] += self.mesh_index_counter

            self.mesh_indicates.extend(indices)
            self.mesh_index_counter += 4

            self.mesh_tex_coord.extend(block_type.texcoord[face])
            self.mesh_shading_value.extend(block_type.shading_values[face])

        for local_x in range(config.SUBCHUNK_WIDTH):
            for local_y in range(config.SUBCHUNK_HEIGHT):
                for local_z in range(config.SUBCHUNK_LENGTH):
                    parent_lx = self._local_position[0] + local_x
                    parent_ly = self._local_position[1] + local_y
                    parent_lz = self._local_position[2] + local_z

                    block_number = self._owner_chunk.blocks[parent_lx][parent_ly][parent_lz]
                    if not block_number:
                        continue
                    
                    block_type = self._world.block_types[block_number]
                    x, y, z = (self._position[0] + local_x, self._position[1] + local_y, self._position[2] + local_z)

					# 只有为cube时才检测相邻面是否需要生成，否则都生成
                    if block_type.is_cube:
                        if not self._world.is_opaque_block((x + 1, y, z)):
                            add_face(0)
                        if not self._world.is_opaque_block((x - 1, y, z)):
                            add_face(1)
                        if not self._world.is_opaque_block((x, y + 1, z)):
                            add_face(2)
                        if not self._world.is_opaque_block((x, y - 1, z)):
                            add_face(3)
                        if not self._world.is_opaque_block((x, y, z + 1)):
                            add_face(4)
                        if not self._world.is_opaque_block((x, y, z - 1)):
                            add_face(5)
                    else:
                        for i in range(len(block_type.vertices)):
                            add_face(i)

