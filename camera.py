import glm
import config

class Camera:
    def __init__(self):
        aspect_ratio = config.WINDOW_RES[0] / config.WINDOW_RES[1]
        self._proj_mat = glm.perspective(config.V_FOV, aspect_ratio, config.NEAR_CULL, config.FAR_CULL)


    def update(self, position, forward, up):
        view_mat = glm.lookAt(position, position + forward, up)

        if (self._shader):
            self._shader.set_uniform_mat4f_by_name("view_mat", view_mat)
            self._shader.set_uniform_mat4f_by_name("proj_mat", self._proj_mat)


    def bind_shader(self, shader):
        self._shader = shader