"""HUD 层：在屏幕上绘制准星等辅助 UI 元素。"""

import imgui


class HUD:
    """绘制屏幕中央十字准星。"""

    def __init__(self, size=10, thickness=2.0, color=(1.0, 1.0, 1.0, 0.8)):
        """初始化 HUD。

        Args:
            size: 十字准星的半臂长度（像素）。
            thickness: 线条粗细。
            color: RGBA 颜色元组，范围 0.0~1.0。
        """
        self.size = size
        self.thickness = thickness
        self.color = color

    def draw(self):
        """在屏幕正中绘制十字准星。"""
        io = imgui.get_io()
        cx = io.display_size.x * 0.5
        cy = io.display_size.y * 0.5
        s = self.size

        color_u32 = imgui.get_color_u32_rgba(*self.color)

        draw_list = imgui.get_background_draw_list()
        # 水平线
        draw_list.add_line(cx - s, cy, cx + s, cy, color_u32, self.thickness)
        # 垂直线
        draw_list.add_line(cx, cy - s, cx, cy + s, color_u32, self.thickness)
