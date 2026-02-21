import glm
import pygame as pg
import config
import math
import hit
import logging
from gui_mgr import HUD

logger = logging.getLogger(__name__)


class Controller:
    """
    处理外部输入
    """
    def __init__(self, world):
        self._position = config.HOME_POS
        self._right = glm.vec3(1, 0, 0)
        self._up = glm.vec3(0, 1, 0)
        self._forward = glm.vec3(0, 0, -1)
        self._yaw = -90
        self._pitch = 0
        self._update_vectors()
        
        self._world = world
        self._chat_box = None
        self._hud = HUD()
        
        self.holding = 1 # 代表手里拿的哪个方块
        
        self.mouse_grabbed = False
        pg.event.set_grab(self.mouse_grabbed)
        pg.mouse.set_visible(not self.mouse_grabbed)
        

    def bind_camera(self, camera):
        self._camera = camera
        
    def bind_plugin(self, plugin):
        self._plugin = plugin

    def bind_chat_box(self, chat_box):
        self._chat_box = chat_box

    def _move_forward(self, value):
        self._position += self._forward * value

    def _move_right(self, value):
        self._position += self._right * value

    def _move_up(self, value):
        self._position += glm.vec3(0, 1, 0) * value

    def _rotate_yaw(self, value):
        self._yaw += value

    def _rotate_pitch(self, value):
        self._pitch -= value
        self._pitch = glm.clamp(self._pitch, -config.PITCH_MAX, config.PITCH_MAX)

    def _keyboard_process(self, delta):
        key_states = pg.key.get_pressed()

        value = delta * config.MOVE_SPEED
        if key_states[pg.K_w]:
            self._move_forward(value)
        if key_states[pg.K_s]:
            self._move_forward(-value)
        if key_states[pg.K_a]:
            self._move_right(-value)
        if key_states[pg.K_d]:
            self._move_right(value)
        if key_states[pg.K_q]:
            self._move_up(value)
        if key_states[pg.K_e]:
            self._move_up(-value)





    def _mouse_process(self):
        dx, dy = pg.mouse.get_rel()

        if dx:
            self._rotate_yaw(dx * config.MOUSE_SENSITIVITY)
        if dy:
            self._rotate_pitch(dy * config.MOUSE_SENSITIVITY)
        

    def _update_vectors(self):
        self._forward.x = glm.cos(glm.radians(self._yaw)) * glm.cos(glm.radians(self._pitch))
        self._forward.y = glm.sin(glm.radians(self._pitch))
        self._forward.z = glm.sin(glm.radians(self._yaw)) * glm.cos(glm.radians(self._pitch))
        
        self._forward = glm.normalize(self._forward)
        self._right = glm.normalize(glm.cross(self._forward, glm.vec3(0, 1, 0)))
        self._up = glm.normalize(glm.cross(self._right, self._forward))
        
    
    def on_mouse_button_down(self, button):
        
        def hit_callback(cur_block, next_block):
            if button == 1:
                #右键
                logger.debug(f"放置方块在 {cur_block}")
                self._world.set_block(cur_block, self.holding)
            elif button == 3:
                #左键
                logger.debug(f"击中方块 {next_block}")
                self._world.set_block(next_block, 0)

        # 将角度制转换为弧度制
        rotate_yaw = math.radians(self._yaw)
        rotate_pitch = math.radians(self._pitch)
        hit_ray = hit.Hit_ray(self._world, (rotate_yaw, rotate_pitch), self._position)
        while hit_ray.distance < hit.HIT_RANGE:
            if hit_ray.step(hit_callback):
                break
            
            
    def on_key_down(self, key):
        # 反引号键：切换聊天框显示
        if key == pg.K_BACKQUOTE:
            if self._chat_box:
                self._chat_box.toggle()
                # 打开聊天框时释放鼠标并启用 IME，关闭时停用 IME
                if self._chat_box.visible:
                    self.mouse_grabbed = False
                    pg.event.set_grab(False)
                    pg.mouse.set_visible(True)
                    pg.key.start_text_input()
                else:
                    pg.key.stop_text_input()
            return

        if key == pg.K_1:
            self.holding = 1
        elif key == pg.K_2:
            self.holding = 2
        elif key == pg.K_3:
            self.holding = 3
        elif key == pg.K_4:
            self.holding = 4
        elif key == pg.K_5:
            self.holding = 5
        elif key == pg.K_6:
            self.holding = 6
        elif key == pg.K_7:
            self.holding = 7
        elif key == pg.K_8:
            self.holding = 8
        elif key == pg.K_9:
            self.holding = 9
            
        if key == pg.K_ESCAPE:
            self.mouse_grabbed = not self.mouse_grabbed
            pg.event.set_grab(self.mouse_grabbed)
            pg.mouse.set_visible(not self.mouse_grabbed)
            
        if key == pg.K_h:
            self._position = config.HOME_POS
        if key == pg.K_j:
            self._plugin._handle_get_scene_info()
        if key == pg.K_r:
            self._world.reset_map()


    def draw_hud(self):
        """绘制 HUD，仅在鼠标被 grab 时显示准星。"""
        if self.mouse_grabbed:
            self._hud.draw()

    def update(self, delta):
        # 鼠标可见时（未 grab），跳过游戏的持续输入处理
        if self.mouse_grabbed:
            self._keyboard_process(delta)
            self._mouse_process()

        self._update_vectors()

        if self._camera:
            self._camera.update(self._position, self._forward, self._up)