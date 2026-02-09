import config
import models.cube


class BlockTypeException(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


class BlockType:
    """
    方块的蓝图定义类
    """
    def __init__(self, texture_mgr, name="unknow", block_face_textures={"all":"cobblestone"}, model=models.cube):
        self.name = name
        self.vertices = model.vertex_positions
        self.texcoord = model.tex_coords.copy()
        self.shading_values = model.shading_values
        self.transparent = model.transparent
        self.is_cube = model.is_cube
        self.block_face_textures = block_face_textures
        self.model = model
        self.glass = model.glass

        def set_block_face(face_id, tex_layer):
            """
            设置方块的face_id使用哪个tex_layer
            """
            if face_id >= len(self.texcoord):
                return

            self.texcoord[face_id] = self.texcoord[face_id].copy()
            for vertex in range(4):
                self.texcoord[face_id][vertex * 3 + 2] = tex_layer

        for face in block_face_textures:
            texture_name = block_face_textures[face]
            tex_layer = texture_mgr.add_texture(texture_name)

            if face == "all":
                for i in range(len(self.texcoord)):
                    set_block_face(i, tex_layer)
            elif face == "sides":
                set_block_face(0, tex_layer)
                set_block_face(1, tex_layer)
                set_block_face(4, tex_layer)
                set_block_face(5, tex_layer)
            elif face == "x":
                set_block_face(0, tex_layer)
                set_block_face(1, tex_layer)
            elif face == "y":
                set_block_face(2, tex_layer)
                set_block_face(3, tex_layer)
            elif face == "z":
                set_block_face(4, tex_layer)
                set_block_face(5, tex_layer)
            else:
                set_block_face(["right", "left", "top", "bottom", "front", "back"].index(face), tex_layer)