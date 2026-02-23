import logging
import math
import threading
import json
from collections import deque

import websocket

logger = logging.getLogger(__name__)


from cmd_builder import build_request, build_response

_ws_url = "ws://localhost:8000/ws"





class AgentPlugin:
    """维护 AIAgent 网关的 WebSocket 连接。"""

    def __init__(self, world, controller):
        self._ws = None
        self.recv_thread = None

        self.recv_queue = deque()
        self.process_queue = deque()

        self._cmd_locker = threading.Lock()

        self.world = world
        self.controller = controller

        self.enable = True
        self._chat_callback = None
        self._session_id = None


    def init(self):
        """外部 init 接口，建立 WebSocket 连接并启动收包线程。"""
        if not self.enable:
            return

        if self._ws is not None:
            logger.warning("ws not none, closing previous connection")
            try:
                self._ws.close()
            except Exception:
                pass

        try:
            logger.info(f"try to connect {_ws_url}...")
            self._ws = websocket.create_connection(_ws_url)
        except Exception as e:
            logger.error(f"failed to connect to {_ws_url}: {e}")
            self._ws = None
            return

        logger.info(f"connect to {_ws_url} success")

        # 开启收包线程
        try:
            self.recv_thread = threading.Thread(target=self._receive, daemon=True)
            self.recv_thread.start()
        except Exception as e:
            logger.error(f"create thread failed: {e}")
            self._ws.close()
            self._ws = None
            raise


    def _receive(self):
        """后台线程：持续接收 WebSocket 消息并放入队列。"""
        try:
            while self._ws is not None:
                try:
                    data = self._ws.recv()
                except websocket.WebSocketConnectionClosedException:
                    logger.warning("websocket connection closed")
                    break
                except Exception as e:
                    logger.error(f"recv error: {e}")
                    break

                if not data:
                    break

                try:
                    command = json.loads(data)
                    with self._cmd_locker:
                        self.recv_queue.append(command)
                except json.JSONDecodeError:
                    logger.warning(f"invalid json: {data[:200]}")
                except Exception as e:
                    logger.error(f"recv parse error: {e}")
        finally:
            logger.info("receive thread exiting")


    def finit(self):
        if not self.enable:
            return

        if self._ws is not None:
            try:
                self._ws.close()
            except Exception as e:
                logger.error(f"failed to disconnect: {e}")
            finally:
                self._ws = None


    def update(self):
        """从 recv_queue 队列中取出操作在主线程中执行。"""
        if not self.enable:
            return

        if not self._ws:
            return

        with self._cmd_locker:
            # 交换队列
            tmp = self.recv_queue
            self.recv_queue = self.process_queue
            self.process_queue = tmp

        while self.process_queue:
            cmd = self.process_queue.popleft()
            logger.info(f"process cmd {cmd}")
            self.process_cmd(cmd)


    def set_chat_callback(self, callback):
        """设置聊天回复回调函数。

        Args:
            callback: 回调函数，签名为 callback(reply, conversation_id)。
        """
        self._chat_callback = callback


    def send_chat(self, text):
        """发送聊天消息到 agent 服务端。

        Args:
            text: 用户输入的消息文本。
        """
        if not self._ws:
            logger.warning("cannot send chat: not connected")
            return

        try:
            message = json.dumps(build_request("chat", {"message": text}))
            self._ws.send(message)
        except Exception as e:
            logger.error(f"send chat error: {e}")


    def _send_json(self, data):
        """发送 JSON 数据到服务端。"""
        if not self._ws:
            logger.error("no available ws to use")
            return
        try:
            self._ws.send(json.dumps(data))
        except Exception as e:
            logger.error(f"send data error: {e}")


    def _handle_connected(self, params):
        """处理服务端连接成功通知。"""
        self._session_id = params.get("session_id", "")
        logger.info(f"connected to server, session_id={self._session_id}")


    def _handle_chat_reply(self, params):
        """处理 agent 聊天回复。"""
        reply = params.get("reply", "")
        conversation_id = params.get("conversation_id", "")
        logger.info(f"chat reply: {reply[:100]}")
        if self._chat_callback:
            self._chat_callback(reply, conversation_id)


    def _handle_hello(self, params):
        logger.info(f"handle hello message {params}")


    def _handle_get_scene_info(self, params, request_id=None):
        logger.info("_handle_get_scene_info")

        scene_info = {
            "camera": {},
            "blocks": [],
        }

        camerainfo = scene_info["camera"]
        camerainfo["pos"] = list(self.controller._position)
        camerainfo["forward"] = list(self.controller._forward)
        camerainfo["up"] = list(self.controller._up)
        camerainfo["right"] = list(self.controller._right)

        scene_info["blocks"] = self.world.get_all_blocks()

        self._send_json(build_response("get_scene_info", "ok", {"scene_info": scene_info}, request_id=request_id))


    def _handle_set_blocks(self, params, request_id=None):
        logger.info(f"_handle_set_blocks params: {params}")

        for block in params["blocks"]:
            block_type = block["type"]
            wx = math.floor(block["wx"])
            wy = math.floor(block["wy"])
            wz = math.floor(block["wz"])

            self.world.set_block((wx, wy, wz), block_type)

        self._send_json(build_response("set_blocks", "ok", {"count": len(params.get("blocks", []))}, request_id=request_id))


    def process_cmd(self, command):
        """处理服务端发来的消息。

        消息格式（与服务端 cmd_dispatch 对齐）:
            请求: {"cmd": "xxx", "request_id": "...", "params": {...}}
            响应: {"cmd": "xxx", "status": "ok|error", "params": {...}}
        """
        handlers = {
            "connected": self._handle_connected,
            "chat": self._handle_chat_reply,
            "hello": self._handle_hello,
            "get_scene_info": self._handle_get_scene_info,
            "set_blocks": self._handle_set_blocks,
        }

        if not self._ws:
            logger.error("no available ws to use")
            return

        cmd_type = command.get("cmd")
        cmd_params = command.get("params", {})
        request_id = command.get("request_id")

        if not cmd_type:
            logger.warning("received message without cmd field")
            return

        handler = handlers.get(cmd_type)
        if handler:
            try:
                # 服务端请求带 request_id 的 handler 需要额外参数
                if request_id is not None:
                    handler(cmd_params, request_id=request_id)
                else:
                    handler(cmd_params)
            except Exception as e:
                logger.error(f"handle cmd error [{cmd_type}]: {e}")
        else:
            logger.warning(f"unknown command: {cmd_type}")
