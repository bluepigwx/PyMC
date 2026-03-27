import socket
import logging
import threading
import struct
import json
import math
from collections import deque

logger = logging.getLogger(__name__)

from cmd_builder import build_request, build_response

_host = "localhost"
_port = 8001

# 长度前缀帧常量（必须与服务端 TcpChannel 一致）
_HEADER_FORMAT = ">I"
_HEADER_SIZE = struct.calcsize(_HEADER_FORMAT)  # 4 字节
_MAX_FRAME_SIZE = 16 * 1024 * 1024  # 16 MB 安全上限


class Plugin:
    def __init__(self, world, controller):
        self.socket = None
        
        self.recv_queue = deque()
        self.process_queue = deque()
        
        self._cmd_locker = threading.Lock()
        
        self.world = world
        self.controller = controller
        
        self.enable = True
        self._chat_callback = None
        self._chat_start_callback = None
        self._chat_delta_callback = None
        self._chat_end_callback = None
        self._session_id = None
        self._streaming_active = False
        self._current_msg_id = None  # 跟踪当前流式消息 ID

    # ------------------------------------------------------------------
    # 底层帧 I/O 辅助方法
    # ------------------------------------------------------------------

    def _recv_exactly(self, n):
        """从 socket 精确接收 *n* 个字节。

        Raises:
            ConnectionError: 对端在所有字节到达前关闭连接。
        """
        buf = bytearray()
        while len(buf) < n:
            chunk = self.socket.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Server disconnected (recv returned empty)")
            buf.extend(chunk)
        return bytes(buf)

    def _recv_frame(self):
        """接收一个长度前缀帧并返回解码后的字符串。

        帧协议（与服务端 TcpChannel 一致）：
            [4 字节大端 uint32: 载荷长度] [UTF-8 载荷]
        """
        header = self._recv_exactly(_HEADER_SIZE)
        (length,) = struct.unpack(_HEADER_FORMAT, header)
        if length > _MAX_FRAME_SIZE:
            raise ConnectionError(
                f"Frame too large: {length} bytes (max {_MAX_FRAME_SIZE})"
            )
        payload = self._recv_exactly(length)
        return payload.decode("utf-8")

    def _send_frame(self, data):
        """将字符串作为一个长度前缀帧发送。

        Args:
            data: 要发送的字符串（将以 UTF-8 编码）。
        """
        payload = data.encode("utf-8")
        header = struct.pack(_HEADER_FORMAT, len(payload))
        self.socket.sendall(header + payload)

    # ------------------------------------------------------------------
    # 连接生命周期
    # ------------------------------------------------------------------

    def init(self):
        """连接服务器并启动接收线程。"""
        if not self.enable:
            return
        
        if self.socket is not None:
            logger.warning("socket not none, closing previous connection")
            try:
                self.socket.close()
            except Exception:
                pass
        
        try:
            logger.info(f"try to connect {_host}:{_port}...")
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((_host, _port))
        except Exception as e:
            logger.error(f"failed to connect to {_host}:{_port} {e}")
            self.socket = None
            return
        
        logger.info(f"connect to {_host}:{_port} success")
        
        # 启动接收线程
        try:
            self.recv_thread = threading.Thread(target=self._receive, daemon=True)
            self.recv_thread.start()
        except Exception as e:
            logger.error(f"create thread failed {e}")
            self.socket.close()
            self.socket = None
            raise
            
        logger.info("create receive thread success")
            
    def _receive(self):
        """后台线程：接收长度前缀帧并入队。"""
        try:
            while self.socket is not None:
                try:
                    text = self._recv_frame()
                except ConnectionError as e:
                    logger.info(f"Server disconnected: {e}")
                    break
                except Exception as e:
                    logger.error(f"recv error: {e}")
                    break

                try:
                    command = json.loads(text)
                    with self._cmd_locker:
                        self.recv_queue.append(command)
                except json.JSONDecodeError:
                    logger.warning(f"invalid json: {text[:200]}")
                except Exception as e:
                    logger.error(f"recv parse error: {e}")
        finally:
            logger.info("receive thread exiting")

    def finit(self):
        if not self.enable:
            return
        
        if self.socket is not None:
            try:
                self.socket.close()
            except Exception as e:
                logger.error(f"failed to disconnect {e}")
            finally:
                self.socket = None
                
    # ------------------------------------------------------------------
    # 主线程更新循环
    # ------------------------------------------------------------------

    def update(self):
        """在主线程上排空 recv_queue 并处理命令。"""
        if not self.enable:
            return
        
        if not self.socket:
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

    # ------------------------------------------------------------------
    # 发送辅助方法
    # ------------------------------------------------------------------

    def _send_json(self, data):
        """将 *data* 序列化为 JSON 并作为长度前缀帧发送。"""
        if not self.socket:
            logger.error("no available socket to use")
            return
        try:
            self._send_frame(json.dumps(data))
        except Exception as e:
            logger.error(f"send data error: {e}")

    def set_chat_callback(self, callback):
        """设置聊天回复回调。

        Args:
            callback: callback(reply, conversation_id)。
        """
        self._chat_callback = callback

    def set_chat_stream_callbacks(self, on_start, on_delta, on_end):
        """设置流式聊天回复的回调。

        Args:
            on_start: function() — 流式开始时调用
            on_delta: function(delta_text) — 每个 token 到达时调用
            on_end:   function() — 流式结束时调用
        """
        self._chat_start_callback = on_start
        self._chat_delta_callback = on_delta
        self._chat_end_callback = on_end

    def send_chat(self, text):
        """向 Agent 服务器发送聊天消息。

        Args:
            text: 用户输入文本。
        """
        if not self.socket:
            logger.warning("cannot send chat: not connected")
            return

        try:
            self._send_json(build_request("stream", {"message": text}))
            logger.info(f"send message {text}")
        except Exception as e:
            logger.error(f"send chat error: {e}")

    # ------------------------------------------------------------------
    # 接收消息处理器
    # ------------------------------------------------------------------

    def _handle_connected(self, params):
        """处理服务器连接通知。"""
        self._session_id = params.get("session_id", "")
        logger.info(f"connected to server, session_id={self._session_id}")

    def _handle_chat_reply(self, params):
        """处理 Agent 聊天回复（非流式回退）。"""
        reply = params.get("reply", "")
        conversation_id = params.get("conversation_id", "")
        logger.info(f"chat reply: {reply[:100]}")
        if self._streaming_active:
            # 流式模式：忽略旧版回调以避免重复
            return
        if self._chat_callback:
            self._chat_callback(reply, conversation_id)

    def _handle_message(self, params):
        """处理 OpenCode 流式消息响应。

        服务端以两种格式转发 OpenCode Bus 事件：

        **透传 SSE 中继格式**（新）：
            {type: "start"}                                  -> 流开始
            {type: "delta", delta: "...", field, messageID}  -> 增量文本
            {type: "message", event: "...", data: {...}}     -> 包装的 Bus 事件
            {type: "status", event: "...", data: {...}}      -> 会话状态
            {type: "end"}                                    -> 流结束

        **旧版格式**：
            {type: "info",   data: {...}}     -> 消息元数据
            {type: "part",   part: {...}}     -> 单个部分
            {type: "data",   chunk: "..."}    -> 批量载荷
            {type: "result", data: {...}}     -> 最终结果
        """
        msg_type = params.get("type", "")

        if msg_type == "start":
            logger.info("message stream started")
            self._streaming_active = True
            self._current_msg_id = None
            if self._chat_start_callback:
                self._chat_start_callback()

        # ---- 透传 SSE 中继：增量 delta ----
        elif msg_type == "delta":
            self._handle_delta(params)

        # ---- 透传 SSE 中继：包装的 Bus 事件 ----
        elif msg_type == "message":
            self._handle_bus_message_event(params)

        # ---- 透传 SSE 中继：会话状态（忽略）----
        elif msg_type == "status":
            event_name = params.get("event", "")
            logger.debug(f"session status event: {event_name}")

        # ---- 旧版格式处理 ----
        elif msg_type == "info":
            info = params.get("data", {})
            sid = info.get("sessionID", "")
            model = info.get("modelID", "")
            logger.info(f"message info: model={model}, session={sid}")

        elif msg_type == "part":
            part = params.get("part", {})
            self._dispatch_part(part)

        elif msg_type == "data":
            chunk_raw = params.get("chunk", "")
            if not chunk_raw:
                return
            if isinstance(chunk_raw, dict):
                self._extract_and_dispatch_parts(chunk_raw)
                return
            try:
                chunk = json.loads(chunk_raw)
            except (json.JSONDecodeError, TypeError):
                logger.debug(f"message data chunk is not json, skipping ({len(chunk_raw)} bytes)")
                return
            self._extract_and_dispatch_parts(chunk)

        elif msg_type == "result":
            result_data = params.get("data", {})
            if result_data:
                self._extract_and_dispatch_parts(result_data)

        elif msg_type == "end":
            logger.info("message stream ended")
            self._streaming_active = False
            self._current_msg_id = None
            if self._chat_end_callback:
                self._chat_end_callback()

        else:
            logger.warning(f"unknown message type: {msg_type}")

    # ------------------------------------------------------------------
    # 透传 SSE 中继处理器
    # ------------------------------------------------------------------

    def _handle_delta(self, params):
        """处理 type='delta'：来自 SSE 中继的增量文本 token。

        参数格式：
            {type: "delta", delta: " hello", field: "text",
             sessionID, messageID, partID}
        """
        delta = params.get("delta", "")
        field = params.get("field", "")
        message_id = params.get("messageID", "")

        if not delta:
            return

        # 如果未发送 'start' 帧，自动检测流开始
        if not self._streaming_active:
            self._streaming_active = True
            self._current_msg_id = message_id
            if self._chat_start_callback:
                self._chat_start_callback()
            logger.info(f"streaming auto-started for message {message_id}")
        elif self._current_msg_id and self._current_msg_id != message_id:
            # 同一流中出现新消息（通常不会发生）
            logger.info(f"message switched from {self._current_msg_id} to {message_id}")
            self._current_msg_id = message_id

        if not self._current_msg_id:
            self._current_msg_id = message_id

        if field == "text":
            if self._chat_delta_callback:
                logger.debug(f"delta: {delta[:80]}")
                self._chat_delta_callback(delta)
            elif self._chat_callback:
                session_id = params.get("sessionID", "")
                self._chat_callback(delta, session_id)

    def _handle_bus_message_event(self, params):
        """处理 type='message'：来自 SSE 中继的包装 OpenCode Bus 事件。

        参数格式：
            {type: "message", event: "message.part.updated",
             data: {type: "...", properties: {...}}}
        """
        event_name = params.get("event", "")
        data = params.get("data", {})
        properties = data.get("properties", {})

        if event_name == "message.part.updated":
            part = properties.get("part", {})
            self._dispatch_part(part)

        elif event_name == "message.updated":
            info = properties.get("info", {})
            role = info.get("role", "")
            time_info = info.get("time", {})
            completed = time_info.get("completed")
            model = info.get("modelID", "")
            if role == "assistant" and completed:
                logger.info(f"message completed: model={model}")
            elif role == "assistant":
                logger.debug(f"message updated: model={model}")

        else:
            logger.debug(f"bus message event: {event_name}")

    def _dispatch_part(self, part):
        """分发单个消息部分（来自旧版 'part' 或 Bus 'message.part.updated'）。

        部分类型：text, reasoning, step-start, step-finish, tool-invocation 等。
        """
        part_type = part.get("type", "")

        if part_type == "text":
            text = part.get("text", "")
            if text:
                session_id = part.get("sessionID", "")
                if self._chat_delta_callback:
                    logger.debug(f"part text: {text[:200]}")
                    self._chat_delta_callback(text)
                elif self._chat_callback:
                    logger.info(f"message reply: {text[:200]}")
                    self._chat_callback(text.strip(), session_id)

        elif part_type == "step-start":
            logger.debug(f"step started: {part.get('id', '')}")

        elif part_type == "step-finish":
            reason = part.get("reason", "")
            tokens = part.get("tokens", {})
            logger.debug(f"step finished: reason={reason}, tokens={tokens.get('total', '?')}")

        elif part_type == "reasoning":
            reasoning_text = part.get("text", "").strip()
            if reasoning_text:
                logger.debug(f"reasoning: {reasoning_text[:100]}")
                if self._chat_delta_callback:
                    self._chat_delta_callback(f"[Reasoning] {reasoning_text}")
                elif self._chat_callback:
                    session_id = part.get("sessionID", "")
                    self._chat_callback(f"[Reasoning] {reasoning_text}", session_id)

        elif part_type == "tool-invocation":
            tool = part.get("toolInvocation", {})
            tool_name = tool.get("toolName", "unknown")
            state = tool.get("state", "")
            logger.info(f"tool call: {tool_name} ({state})")

        else:
            logger.debug(f"unhandled part type: {part_type}")

    def _extract_and_dispatch_parts(self, payload):
        """从旧版 OpenCode 消息载荷中提取文本部分并分发。

        Args:
            payload: 包含 'parts' 列表和可选 'info' 的字典。
        """
        parts = payload.get("parts", [])
        texts = []
        for part in parts:
            if part.get("type") == "text":
                texts.append(part.get("text", ""))

        if texts:
            reply = "".join(texts).strip()
            session_id = payload.get("info", {}).get("sessionID", "")
            logger.info(f"message reply: {reply[:200]}")
            if self._chat_delta_callback:
                self._chat_delta_callback(reply)
            elif self._chat_callback:
                self._chat_callback(reply, session_id)

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

    def _expand_regions(self, regions):
        """将区域定义展开为 (type, wx, wy, wz) 元组的扁平列表。"""
        blocks = []
        for region in regions:
            block_type = region["type"]
            x_range = region["x"]
            y_range = region["y"]
            z_range = region["z"]

            # 构建排除集合用于 O(1) 查找
            exclude_set = set()
            for ex in region.get("exclude", []):
                exclude_set.add((ex["x"], ex["y"], ex["z"]))

            # 构建覆盖映射: (x, y, z) -> type
            override_map = {}
            for ov in region.get("override", []):
                override_map[(ov["x"], ov["y"], ov["z"])] = ov["type"]

            for y in range(y_range[0], y_range[1] + 1):
                for x in range(x_range[0], x_range[1] + 1):
                    for z in range(z_range[0], z_range[1] + 1):
                        if (x, y, z) in exclude_set:
                            continue
                        t = override_map.get((x, y, z), block_type)
                        blocks.append((t, x, y, z))

        return blocks

    def _handle_set_blocks_region(self, params, request_id=None):
        """处理基于区域的方块放置。"""
        regions = params.get("regions", [])
        if not regions:
            logger.warning("set_blocks_region: empty regions")
            self._send_json(build_response("set_blocks_region", "error", {"message": "empty regions"}, request_id=request_id))
            return

        blocks = self._expand_regions(regions)
        logger.info(f"set_blocks_region: {len(regions)} regions -> {len(blocks)} blocks")

        for block_type, wx, wy, wz in blocks:
            self.world.set_block((wx, wy, wz), block_type)

        self._send_json(build_response("set_blocks_region", "ok", {"count": len(blocks)}, request_id=request_id))
    
    # ------------------------------------------------------------------
    # 命令分发
    # ------------------------------------------------------------------

    def process_cmd(self, command):
        """处理来自服务器的消息。

        消息格式（与服务端 cmd_dispatch 对齐）：
            请求:  {"cmd": "xxx", "request_id": "...", "params": {...}}
            响应: {"cmd": "xxx", "status": "ok|error", "params": {...}}
        """
        handlers = {
            "connected": self._handle_connected,
            "chat": self._handle_chat_reply,
            "stream": self._handle_message,
            "hello": self._handle_hello,
            "get_scene_info": self._handle_get_scene_info,
            "set_blocks": self._handle_set_blocks,
            "set_blocks_region": self._handle_set_blocks_region,
        }
        
        if not self.socket:
            logger.error("no available socket to use")
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
                # 带 request_id 的服务端请求需要额外参数
                if request_id is not None:
                    handler(cmd_params, request_id=request_id)
                else:
                    handler(cmd_params)
            except Exception as e:
                logger.error(f"handle cmd error [{cmd_type}]: {e}")
        else:
            logger.warning(f"unknown command: {cmd_type}")