import glm
import numpy as np

# 窗口配置（当前显示器 2560x1440）
# 可选：1280x720 / 1600x900 / 1920x1080 / 2560x1440（全屏大小）
WINDOW_RES = (1600, 900)


# 控制配置
MOVE_SPEED = 0.01
MOUSE_SENSITIVITY = 0.05
PITCH_MAX = 89

# 相机配置
NEAR_CULL = 0.1
FAR_CULL = 2000.0
FOV_DEG = 50
V_FOV = glm.radians(FOV_DEG)  # vertical FOV
HOME_POS = glm.vec3(10, 2, 10)
#HOME_POS = glm.vec3(0, 100, 10)


#Chunk配置
CHUNK_WIDHT = 16
CHUNK_HEIGHT = 128
CHUNK_LENGHTH = 16

# 默认平坦草地的大小：以世界原点为中心，x/z 方向各覆盖这么多个 chunk
# 8 个 chunk = 128 格，草地范围 x/z ∈ [-128, 127]
DEFAULT_MAP_HALF_CHUNKS = 8


SUBCHUNK_WIDTH = 4
SUBCHUNK_HEIGHT = 4
SUBCHUNK_LENGTH = 4

# TCP Agent 插件：启动时是否主动连接 localhost:8001 的 Agent 服务端
# （tcp_agent_plugin.py）。默认不连，需要时（如配合 scene_server.py 测试）打开
TCP_AGENT_ENABLED = False
