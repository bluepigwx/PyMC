import pygame as pg
from OpenGL.GL import *
import glm
import imgui
import config
import shader
import camera
import controller
import world
import logging
import os
import sys
from gui_mgr import ChatBox, PygameCoreRenderer
import tcp_agent_plugin
import mcp_server

logging.basicConfig(level=logging.DEBUG,
                    format="[%(asctime)s][%(filename)s:%(funcName)s:%(lineno)d][%(levelname)s][%(message)s]",
                    handlers=[
                        logging.StreamHandler()
                    ])

logger = logging.getLogger("application")

class Application:
    def __init__(self, scene_path=None):
        self._run = False
        self._imgui_impl = None
        self._chat_box = None
        self._mcp = None
        self._scene_path = scene_path


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

        # 初始化 imgui
        imgui.create_context()
        self._imgui_impl = PygameCoreRenderer()

        # 默认关闭 IME，聊天框打开时再启用
        pg.key.stop_text_input()

        self._world = world.World()
        
        logger.info(f"try load map data...")
        self._world.load_map(self._scene_path)
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

        # 从场景文件载入时，默认出生点很可能埋在地下，挪到地表上方
        if self._scene_path:
            spawn = self._find_spawn()
            self._controller._position = spawn
            config.HOME_POS = glm.vec3(spawn)
            logger.info(f"spawn at {tuple(round(v, 1) for v in spawn)}")
        
        logger.info(f"init plugin...")
        # 想换成 OpenCode 网关时：
        #   from gui_mgr.opencode_agent_plugin import OpenCodePlugin
        #   self._plugin = OpenCodePlugin(self._world, self._controller)
        self._plugin = tcp_agent_plugin.Plugin(self._world, self._controller)
        self._plugin.init()
        
        # 初始化聊天框并绑定回调（使用 TCP plugin）
        self._chat_box = ChatBox(self._plugin)
        self._plugin.set_chat_callback(self._chat_box.on_chat_reply)
        self._plugin.set_chat_stream_callbacks(
            self._chat_box.on_chat_start,
            self._chat_box.on_chat_delta,
            self._chat_box.on_chat_end,
        )
        
        self._controller.bind_plugin(self._plugin)
        self._controller.bind_chat_box(self._chat_box)

        logger.info(f"init mcp plugin...")
        self._mcp = mcp_server.Plugin(self._world, self._controller)
        self._mcp.init()


    def _find_spawn(self, x=8, z=8):
        """在 (x,z) 这一列从上往下找第一个非空方块，站到它上面 2 格。"""
        for y in range(config.CHUNK_HEIGHT - 1, -1, -1):
            if self._world.get_block_number(x, y, z) != 0:
                return glm.vec3(x + 0.5, y + 2.5, z + 0.5)
        return glm.vec3(config.HOME_POS)


    def run(self):
        while self._run:
            for event in pg.event.get():
                if event.type == pg.QUIT:
                    self._run = False
                
                # 将事件转发给 imgui
                self._imgui_impl.process_event(event)
                
                # 鼠标可见时（未 grab），imgui 捕获所有输入，仅保留反引号键
                mouse_visible = not self._controller.mouse_grabbed
                
                # 反引号键和 ESC 键始终由 controller 处理
                if event.type == pg.KEYDOWN and event.key in (pg.K_BACKQUOTE, pg.K_ESCAPE):
                    self._controller.on_key_down(event.key)
                elif event.type == pg.KEYDOWN and not mouse_visible:
                    self._controller.on_key_down(event.key)
                if event.type == pg.MOUSEBUTTONDOWN and not mouse_visible:
                    self._controller.on_mouse_button_down(event.button)
            
            delta = self._clock.tick()

            self._update(delta)

            self._begin_render()
            
            self._draw(delta)

            self._draw_gui()
            
            self._end_render()


    def _update(self, delta):
        self._plugin.update()

        if self._mcp:
            self._mcp.update()

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


    def _draw_gui(self):
        """绘制 imgui GUI 层。"""
        # 保存 3D 渲染使用的 GL 状态
        prev_blend = glIsEnabled(GL_BLEND)
        prev_depth = glIsEnabled(GL_DEPTH_TEST)
        prev_cull = glIsEnabled(GL_CULL_FACE)
        prev_scissor = glIsEnabled(GL_SCISSOR_TEST)

        self._imgui_impl.process_inputs()
        imgui.new_frame()

        self._controller.draw_hud()
        self._chat_box.draw()

        imgui.render()
        self._imgui_impl.render(imgui.get_draw_data())

        # 恢复 GL 状态
        if prev_depth:
            glEnable(GL_DEPTH_TEST)
        else:
            glDisable(GL_DEPTH_TEST)
        if prev_blend:
            glEnable(GL_BLEND)
        else:
            glDisable(GL_BLEND)
        if prev_cull:
            glEnable(GL_CULL_FACE)
        else:
            glDisable(GL_CULL_FACE)
        if prev_scissor:
            glEnable(GL_SCISSOR_TEST)
        else:
            glDisable(GL_SCISSOR_TEST)


    def exit(self):
        if self._mcp:
            self._mcp.finit()

        if self._plugin:
            self._plugin.finit()

        if self._imgui_impl:
            self._imgui_impl.shutdown()

        pg.quit()


def _parse_args(argv):
    """解析命令行。

    用法:
        python main.py                        生成默认的平坦草地
        python main.py <场景文件>              载入指定场景
        python main.py --scene <场景文件>      同上
        python main.py --default              强制用默认草地
    """
    import argparse

    parser = argparse.ArgumentParser(description="PyMC")
    parser.add_argument("scene", nargs="?", default=None,
                        help=f"场景文件路径，省略时若 {world.DEFAULT_SCENE_PATH} 存在则自动载入")
    parser.add_argument("--scene", dest="scene_opt", default=None,
                        help="同位置参数 scene")
    parser.add_argument("--default", action="store_true",
                        help="忽略场景文件，生成默认平坦草地")
    args = parser.parse_args(argv)

    if args.default:
        return None

    path = args.scene_opt or args.scene
    if path:
        return path

    # 都没给：默认场景文件存在就用它
    if os.path.exists(world.DEFAULT_SCENE_PATH):
        return world.DEFAULT_SCENE_PATH
    return None


if __name__ == "__main__":
    scene_path = _parse_args(sys.argv[1:])

    app = None
    try:
        app = Application(scene_path=scene_path)

        app.init()

        if scene_path:
            pg.display.set_caption(f"PyMC - {scene_path}")

        app.run()
    except Exception:
        logger.exception("application crashed")
    finally:
        if app:
            try:
                app.exit()
            except Exception:
                logger.exception("error during exit")