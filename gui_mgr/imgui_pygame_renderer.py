"""兼容 OpenGL 3.3 Core Profile 的 imgui Pygame 渲染器。

pyimgui 自带的 PygameRenderer 继承自 FixedPipelineRenderer，
其 refresh_font_texture 使用 GL_ALPHA，在 Core Profile 下会报错。
本模块继承 ProgrammablePipelineRenderer（使用 GL_RGBA），
并搬入 PygameRenderer 中的 Pygame 事件/输入处理逻辑。
"""

import os
import logging

import pygame
import imgui
from imgui.integrations.opengl import ProgrammablePipelineRenderer

logger = logging.getLogger(__name__)

# 常见中文字体路径（Windows）
_CJK_FONT_CANDIDATES = [
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name)
    for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc")
]


def _find_cjk_font():
    """查找系统中可用的中文字体文件路径。"""
    for path in _CJK_FONT_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


class PygameCoreRenderer(ProgrammablePipelineRenderer):
    """基于 ProgrammablePipelineRenderer 的 Pygame 集成渲染器。"""

    # Pygame key → imgui key 映射
    PYGAME_KEY_MAP = {
        pygame.K_TAB: imgui.KEY_TAB,
        pygame.K_LEFT: imgui.KEY_LEFT_ARROW,
        pygame.K_RIGHT: imgui.KEY_RIGHT_ARROW,
        pygame.K_UP: imgui.KEY_UP_ARROW,
        pygame.K_DOWN: imgui.KEY_DOWN_ARROW,
        pygame.K_PAGEUP: imgui.KEY_PAGE_UP,
        pygame.K_PAGEDOWN: imgui.KEY_PAGE_DOWN,
        pygame.K_HOME: imgui.KEY_HOME,
        pygame.K_END: imgui.KEY_END,
        pygame.K_INSERT: imgui.KEY_INSERT,
        pygame.K_DELETE: imgui.KEY_DELETE,
        pygame.K_BACKSPACE: imgui.KEY_BACKSPACE,
        pygame.K_SPACE: imgui.KEY_SPACE,
        pygame.K_RETURN: imgui.KEY_ENTER,
        pygame.K_ESCAPE: imgui.KEY_ESCAPE,
        pygame.K_KP_ENTER: imgui.KEY_PAD_ENTER,
        pygame.K_a: imgui.KEY_A,
        pygame.K_c: imgui.KEY_C,
        pygame.K_v: imgui.KEY_V,
        pygame.K_x: imgui.KEY_X,
        pygame.K_y: imgui.KEY_Y,
        pygame.K_z: imgui.KEY_Z,
    }

    def __init__(self):
        # 必须在 super().__init__() 之前加载中文字体，
        # 因为父类构造函数会调用 refresh_font_texture() 构建字体纹理。
        # 如果在之后添加字体，纹理中不会包含中文字形。
        io = imgui.get_io()
        cjk_font = _find_cjk_font()
        if cjk_font:
            logger.info(f"loading CJK font: {cjk_font}")
            io.fonts.add_font_from_file_ttf(
                cjk_font,
                16.0,
                glyph_ranges=io.fonts.get_glyph_ranges_chinese_full(),
            )
        else:
            logger.warning("no CJK font found, Chinese characters may not display")

        super().__init__()

        self._gui_time = None

        # imgui key_map 值必须在 -1..511 范围内，
        # 但 Pygame 的某些键常量（如 K_KP_ENTER）远超 512，
        # 因此分配一个间接索引（0..N）作为 key_map 值，
        # 并在 process_event 中通过反查表转换。
        self._pygame_to_slot = {}
        for slot, (pygame_key, imgui_key) in enumerate(self.PYGAME_KEY_MAP.items()):
            io.key_map[imgui_key] = slot
            self._pygame_to_slot[pygame_key] = slot

        display_size = pygame.display.get_surface().get_size()
        io.display_size = display_size

    def process_event(self, event):
        """将 Pygame 事件转发给 imgui IO。"""
        io = imgui.get_io()

        if event.type == pygame.MOUSEMOTION:
            io.mouse_pos = event.pos

        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                io.mouse_down[0] = True
            elif event.button == 2:
                io.mouse_down[2] = True
            elif event.button == 3:
                io.mouse_down[1] = True
            elif event.button == 4:
                io.mouse_wheel = 1
            elif event.button == 5:
                io.mouse_wheel = -1

        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                io.mouse_down[0] = False
            elif event.button == 2:
                io.mouse_down[2] = False
            elif event.button == 3:
                io.mouse_down[1] = False

        elif event.type == pygame.KEYDOWN:
            slot = self._pygame_to_slot.get(event.key)
            if slot is not None:
                io.keys_down[slot] = True
            elif event.key < 512:
                io.keys_down[event.key] = True
            io.key_shift = (event.mod & pygame.KMOD_SHIFT) != 0
            io.key_ctrl = (event.mod & pygame.KMOD_CTRL) != 0
            io.key_alt = (event.mod & pygame.KMOD_ALT) != 0
            io.key_super = (event.mod & pygame.KMOD_META) != 0

        elif event.type == pygame.KEYUP:
            slot = self._pygame_to_slot.get(event.key)
            if slot is not None:
                io.keys_down[slot] = False
            elif event.key < 512:
                io.keys_down[event.key] = False
            io.key_shift = (event.mod & pygame.KMOD_SHIFT) != 0
            io.key_ctrl = (event.mod & pygame.KMOD_CTRL) != 0
            io.key_alt = (event.mod & pygame.KMOD_ALT) != 0
            io.key_super = (event.mod & pygame.KMOD_META) != 0

        elif event.type == pygame.TEXTINPUT:
            for char in event.text:
                io.add_input_character(ord(char))

    def process_inputs(self):
        """更新 imgui IO 的 display_size 和 delta_time。"""
        io = imgui.get_io()

        surface = pygame.display.get_surface()
        if surface is not None:
            io.display_size = surface.get_size()

        current_time = pygame.time.get_ticks() / 1000.0
        if self._gui_time is not None:
            io.delta_time = current_time - self._gui_time
        else:
            io.delta_time = 1.0 / 60.0
        if io.delta_time <= 0.0:
            io.delta_time = 1.0 / 60.0
        self._gui_time = current_time
