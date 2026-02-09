from OpenGL.GL import *
import pygame as pg


class TextureMgr:
    """
    纹理数组管理器，当需要时进行惰性加载
    """
    def __init__(self, texture_width, texture_height, max_texture):
        self._texture_width = texture_width
        self._texture_height = texture_height
        self._max_texture = max_texture

        #所有加载过的纹理的名字
        self._textures = []
        #纹理数组对象句柄
        self.texture_array = 0


    def init(self):
        self.texture_array = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D_ARRAY, self.texture_array)
        glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_WRAP_S, GL_REPEAT)
        glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_WRAP_T, GL_REPEAT)

        glTexImage3D(
            GL_TEXTURE_2D_ARRAY,
            0,
            GL_RGBA,
            self._texture_width,
            self._texture_height,
            self._max_texture,
            0,
            GL_RGBA,
            GL_UNSIGNED_BYTE,
            None
            )


    def add_texture(self, texture):
        """
        惰性加载
        """
        if texture not in self._textures:
            image_surface = pg.image.load(f"textures/{texture}.png")
            width = image_surface.get_width()
            height = image_surface.get_height()

            if width != self._texture_width or height != self._texture_height:
                raise Exception(f"invalid png {texture} param w: {width} h: {height}")

            image_surface = image_surface.convert_alpha()
            image_data = pg.image.tostring(image_surface, "RGBA", True)

            self._textures.append(texture)

            glBindTexture(GL_TEXTURE_2D_ARRAY, self.texture_array)
            glTexSubImage3D(
                GL_TEXTURE_2D_ARRAY,
                0,
                0,
                0,
                self._textures.index(texture),
                self._texture_width,
                self._texture_height,
                1,
                GL_RGBA,
                GL_UNSIGNED_BYTE,
                image_data
            )

        return self._textures.index(texture)


    def gen_mipmap(self):
        """
        在加载完所有纹理后生成最终的mipmap
        """
        if len(self._textures) == 0:
            return
        
        glBindTexture(GL_TEXTURE_2D_ARRAY, self.texture_array)
        glGenerateMipmap(GL_TEXTURE_2D_ARRAY)

