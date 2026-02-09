import pygame as pg
from OpenGL.GL import *
import config
import shader
import camera
import controller
import world
import hit
import math
import glm
import logging
import plugin

logging.basicConfig(level=logging.DEBUG,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                    handlers=[
                        logging.StreamHandler()
                    ])

logger = logging.getLogger("application")

class Application:
    def __init__(self):
        self._run = False


    def init(self):
        pg.init()

        pg.display.gl_set_attribute(pg.GL_CONTEXT_MAJOR_VERSION, 3)
        pg.display.gl_set_attribute(pg.GL_CONTEXT_MINOR_VERSION, 3)
        pg.display.gl_set_attribute(pg.GL_CONTEXT_PROFILE_MASK, pg.GL_CONTEXT_PROFILE_CORE)
        pg.display.set_mode(config.WINDOW_RES, pg.OPENGL | pg.DOUBLEBUF)

        glClearColor(0.1, 0.1, 0.1, 1)
        glEnable(GL_DEPTH_TEST)

        self._clock = pg.time.Clock()
        self._run = True

        self._world = world.World()
        
        logger.info(f"try load map data...")
        self._world.load_map()
        logger.info(f"try build shaders...")
        self._shader = shader.Shader("shaders/vertex_shader.vs", "shaders/fragment_shader.fs")
        self._shader.use()

        self._shader_sampler_location = self._shader.get_uniform("texture_array_sampler")

        logger.info(f"init camera...")
        self._camera = camera.Camera()
        self._camera.bind_shader(self._shader)

        logger.info(f"init controller...")
        self._controller = controller.Controller(self._world)
        self._controller.bind_camera(self._camera)
        
        logger.info(f"init plugin...")
        self._plugin = plugin.Plugin(self._world, self._controller)
        self._plugin.init()
        
        self._controller.bind_plugin(self._plugin)
        
        
    def run(self):
        while self._run:
            for event in pg.event.get():
                if event.type == pg.QUIT:
                    self._run = False
                if event.type == pg.MOUSEBUTTONDOWN:
                    self._controller.on_mouse_button_down(event.button)
                if event.type == pg.KEYDOWN:
                    self._controller.on_key_down(event.key)
            
            delta = self._clock.tick()

            self._update(delta)

            self._begin_render()
            
            self._draw(delta)
            
            self._end_render()


    def _update(self, delta):
        self._plugin.update()
        self._controller.update(delta)


    def _begin_render(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)


    def _end_render(self):
        pg.display.flip()


    def _draw(self, delta):
        self._shader.use()

        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D_ARRAY, self._world.texture_mgr.texture_array)
        glUniform1i(self._shader_sampler_location, 0)

        self._world.draw()


    def exit(self):
        if not self._run:
            return
        
        if self._plugin:
            self._plugin.finit()
        
        pg.quit()


if __name__ == "__main__":
    try:
        app = Application()

        app.init()

        app.run()

        app.exit()
    except Exception as e:
        logger.error(f"{e}")