"""OpenCode Agent 插件：与 OpenCode 服务器的双通道 HTTP 通信。

本插件使用两个通道与 OpenCode 通信：
1. POST /session/{id}/message  — 发送用户消息（完成时返回 ndjson）
2. GET  /event                 — 持久 SSE 流，用于实时增量推送

SSE 事件流通过 `message.part.delta` 事件推送增量文本，
实现逐 token 的流式输出到 UI。

OpenCode API 参考：https://github.com/sst/opencode
默认端点：http://localhost:4096
"""

import logging
import threading
import json
import time
import requests
from collections import deque

logger = logging.getLogger(__name__)

# OpenCode 服务器配置
_OPENCODE_BASE_URL = "http://localhost:4096"
_SESSION_ID = "ses_2d680558fffessmUvMSvZpmC2R"

# SSE 重连间隔（秒）
_SSE_RECONNECT_DELAY = 3


class OpenCodePlugin:
    """通过 HTTP + SSE 与 OpenCode 通信的 Agent 插件。

    双通道架构：
    - 后台 SSE 线程连接 GET /event 实现实时流式传输
    - send_chat() 通过 POST /session/{id}/message 触发 AI 生成
    - SSE 事件（message.part.delta）将增量文本传递到 UI

    提供与 tcp_agent_plugin.Plugin 相同的接口，可作为直接替换使用。
    """

    def __init__(self, world=None, controller=None):
        self.world = world
        self.controller = controller

        self.enable = True
        self._connected = False
        self._chat_callback = None
        self._chat_start_callback = None
        self._chat_delta_callback = None
        self._chat_end_callback = None
        self._session_id = _SESSION_ID

        # 线程安全的消息队列，用于主线程分发
        self._msg_queue = deque()
        self._queue_lock = threading.Lock()

        # SSE 事件流线程
        self._sse_thread = None
        self._sse_stop_event = threading.Event()

        # POST 线程（同一时间只有一个）
        self._post_thread = None

        # 跟踪当前正在流式传输的助手消息
        self._current_msg_lock = threading.Lock()
        self._current_msg_id = None
        self._streaming_text = ""       # 当前消息的累积增量文本
        self._streaming_active = False  # 等待 AI 响应时为 True

    # ------------------------------------------------------------------
    # 连接生命周期
    # ------------------------------------------------------------------

    def init(self):
        """初始化插件并验证 OpenCode 服务器是否可达。"""
        if not self.enable:
            return

        logger.info(f"checking OpenCode server at {_OPENCODE_BASE_URL}...")
        try:
            resp = requests.get(
                f"{_OPENCODE_BASE_URL}/session",
                timeout=5,
            )
            if resp.status_code == 200:
                self._connected = True
                logger.info("OpenCode server is reachable")
                try:
                    data = resp.json()
                    sessions = data if isinstance(data, list) else data.get("sessions", [])
                    if sessions:
                        logger.info(f"found {len(sessions)} session(s)")
                except Exception:
                    pass
            else:
                logger.warning(
                    f"OpenCode server returned status {resp.status_code}, "
                    f"will try to send messages anyway"
                )
                self._connected = True
        except requests.ConnectionError:
            logger.error(
                f"cannot reach OpenCode server at {_OPENCODE_BASE_URL}. "
                f"Make sure OpenCode is running (opencode --server)"
            )
            self._connected = False
        except Exception as e:
            logger.error(f"failed to check OpenCode server: {e}")
            self._connected = False

        # 启动持久 SSE 事件流
        if self._connected:
            self._start_sse_thread()

    def finit(self):
        """关闭插件。"""
        if not self.enable:
            return
        self._sse_stop_event.set()
        self._connected = False
        logger.info("OpenCode plugin shutdown")

    # ------------------------------------------------------------------
    # SSE 事件流（持久后台线程）
    # ------------------------------------------------------------------

    def _start_sse_thread(self):
        """启动后台 SSE 事件流线程。"""
        self._sse_stop_event.clear()
        self._sse_thread = threading.Thread(
            target=self._sse_event_loop,
            daemon=True,
            name="opencode-sse",
        )
        self._sse_thread.start()
        logger.info("SSE event stream thread started")

    def _sse_event_loop(self):
        """后台循环：连接 GET /event 并处理 SSE 事件。

        断开连接时自动重连。
        """
        while not self._sse_stop_event.is_set():
            try:
                self._connect_sse()
            except Exception as e:
                if self._sse_stop_event.is_set():
                    break
                logger.warning(f"SSE connection error: {e}, reconnecting in {_SSE_RECONNECT_DELAY}s...")
            # 重连前等待
            self._sse_stop_event.wait(_SSE_RECONNECT_DELAY)

        logger.info("SSE event loop exited")

    def _connect_sse(self):
        """连接 SSE 事件流并处理事件。"""
        url = f"{_OPENCODE_BASE_URL}/event"
        logger.info(f"connecting to SSE event stream: {url}")

        resp = requests.get(
            url,
            headers={"Accept": "text/event-stream"},
            stream=True,
            timeout=(10, None),  # 10秒连接超时，无读取超时
        )

        if resp.status_code != 200:
            logger.error(f"SSE event stream returned {resp.status_code}: {resp.text[:500]}")
            return

        logger.info("SSE event stream connected")

        # 解析 SSE 格式："data: {...}\n\n"
        data_buffer = []
        for line in resp.iter_lines(decode_unicode=True):
            if self._sse_stop_event.is_set():
                break

            if line is None:
                continue

            if line == "":
                # 空行 = SSE 事件结束
                if data_buffer:
                    data_str = "\n".join(data_buffer)
                    self._handle_sse_event(data_str)
                    data_buffer = []
                continue

            if line.startswith("data:"):
                data_buffer.append(line[5:].strip())
            elif line.startswith(":"):
                # SSE 注释 / 心跳，忽略
                pass
            # event: 行被忽略，因为我们从 data 载荷中解析类型

        logger.info("SSE event stream disconnected")

    def _handle_sse_event(self, data_str):
        """处理来自 /event 流的单个 SSE 事件。

        OpenCode Bus 的关键事件类型：
        - message.part.delta: 增量文本（逐 token）
        - message.part.updated: 部分已更新
        - message.updated: 消息元数据已更新
        - session.updated: 会话状态变更
        - server.heartbeat: 心跳保活
        """
        if not data_str:
            return

        try:
            event = json.loads(data_str)
        except json.JSONDecodeError:
            logger.debug(f"SSE non-JSON data: {data_str[:200]}")
            return

        event_type = event.get("type", "")
        properties = event.get("properties", {})

        if event_type == "message.part.delta":
            self._on_part_delta(properties)

        elif event_type == "message.part.updated":
            self._on_part_updated(properties)

        elif event_type == "message.updated":
            self._on_message_updated(properties)

        elif event_type == "session.updated":
            # 会话状态变更（如 busy -> idle）
            info = properties.get("info", {})
            session_id = info.get("id", "")
            if session_id == self._session_id:
                logger.debug(f"session updated: {info.get('title', '')}")

        elif event_type == "session.error":
            session_id = properties.get("sessionID", "")
            if session_id == self._session_id or not session_id:
                error = properties.get("error", {})
                error_msg = error.get("message", str(error)) if isinstance(error, dict) else str(error)
                logger.error(f"session error: {error_msg}")
                self._enqueue_message({
                    "type": "error",
                    "text": f"[OpenCode error: {error_msg}]",
                })

        elif event_type == "server.heartbeat":
            pass  # 静默忽略心跳

        elif event_type == "server.connected":
            logger.info("SSE server.connected event received")

        else:
            logger.debug(f"SSE event: {event_type}")

    def _on_part_delta(self, properties):
        """处理 message.part.delta：增量文本流式传输。

        属性：
            sessionID, messageID, partID, field, delta
        """
        session_id = properties.get("sessionID", "")
        if session_id != self._session_id:
            return

        message_id = properties.get("messageID", "")
        field = properties.get("field", "")
        delta = properties.get("delta", "")

        if not delta:
            return

        with self._current_msg_lock:
            # 跟踪当前正在流式传输的消息
            if self._current_msg_id is None or self._current_msg_id != message_id:
                # 新消息开始
                if self._streaming_text:
                    # 如果有上一条消息则先刷新
                    self._flush_streaming_text()
                self._current_msg_id = message_id
                self._streaming_text = ""
                self._streaming_active = True
                self._enqueue_message({"type": "start"})
                logger.info(f"streaming started for message {message_id}")

            if field == "text":
                self._streaming_text += delta
                # 将增量入队以实时更新 UI
                self._enqueue_message({
                    "type": "delta",
                    "delta": delta,
                    "message_id": message_id,
                })

    def _on_part_updated(self, properties):
        """处理 message.part.updated：某个部分已完全更新。"""
        part = properties.get("part", {})
        session_id = part.get("sessionID", "")
        if session_id != self._session_id:
            return

        part_type = part.get("type", "")
        if part_type == "tool-invocation":
            tool_name = part.get("toolInvocation", {}).get("toolName", "unknown")
            state = part.get("toolInvocation", {}).get("state", "")
            logger.info(f"tool call: {tool_name} ({state})")
            if state == "call":
                self._enqueue_message({
                    "type": "tool_call",
                    "tool_name": tool_name,
                    "message_id": part.get("messageID", ""),
                })

    def _on_message_updated(self, properties):
        """处理 message.updated：消息元数据变更。

        当助手消息完成时，其 time.completed 字段会被设置。
        我们以此作为刷新累积文本的信号。
        """
        info = properties.get("info", {})
        if info.get("role") != "assistant":
            return

        session_id = info.get("sessionID", "")
        if session_id != self._session_id:
            return

        time_info = info.get("time", {})
        completed = time_info.get("completed")

        if completed:
            with self._current_msg_lock:
                message_id = info.get("id", "")
                if self._current_msg_id == message_id and self._streaming_active:
                    self._flush_streaming_text()
                    logger.info(f"message {message_id} completed")

    def _flush_streaming_text(self):
        """将累积的流式文本作为完整消息刷新。

        必须在持有 _current_msg_lock 的情况下调用。
        """
        if self._streaming_text.strip():
            self._enqueue_message({
                "type": "complete",
                "text": self._streaming_text.strip(),
                "message_id": self._current_msg_id or "",
            })
        self._enqueue_message({"type": "end"})
        self._streaming_text = ""
        self._current_msg_id = None
        self._streaming_active = False

    # ------------------------------------------------------------------
    # 主线程更新循环
    # ------------------------------------------------------------------

    def update(self):
        """在主线程上处理排队的消息。

        每帧由游戏循环调用。排空消息队列并分发回调。
        """
        if not self.enable:
            return

        messages = []
        with self._queue_lock:
            while self._msg_queue:
                messages.append(self._msg_queue.popleft())

        for msg in messages:
            self._dispatch_message(msg)

    # ------------------------------------------------------------------
    # 聊天接口
    # ------------------------------------------------------------------

    def set_chat_callback(self, callback):
        """设置聊天回复回调（非流式回退）。

        Args:
            callback: function(reply_text, session_id)
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
        """向 OpenCode 发送聊天消息。

        通过 POST /session/{id}/message 触发 AI 生成。
        响应通过 SSE 事件流（message.part.delta）返回。

        Args:
            text: 用户输入文本。
        """
        if not self.enable:
            logger.warning("plugin is disabled")
            return

        if not self._connected:
            logger.warning("cannot send chat: not connected to OpenCode")
            if self._chat_callback:
                self._enqueue_message({
                    "type": "error",
                    "text": "[Not connected to OpenCode server]",
                })
            return

        logger.info(f"send message: {text[:200]}")

        # 在后台线程中 POST（非阻塞）
        self._post_thread = threading.Thread(
            target=self._post_message,
            args=(text,),
            daemon=True,
            name="opencode-post",
        )
        self._post_thread.start()

    # ------------------------------------------------------------------
    # POST 消息（后台线程）
    # ------------------------------------------------------------------

    def _post_message(self, text):
        """后台线程：POST 消息以触发 AI 生成。

        实际的流式响应通过 SSE /event 通道传递。
        此 POST 仅触发生成并等待 ndjson 响应确认完成。
        """
        url = f"{_OPENCODE_BASE_URL}/session/{self._session_id}/message"

        try:
            resp = requests.post(
                url,
                json={
                    "parts": [
                        {
                            "type": "text",
                            "text": text,
                        }
                    ]
                },
                headers={
                    "Accept": "application/x-ndjson",
                    "Content-Type": "application/json",
                },
                stream=True,
                timeout=300,  # 复杂任务的长超时
            )

            if resp.status_code != 200:
                logger.error(
                    f"OpenCode API returned {resp.status_code}: "
                    f"{resp.text[:500]}"
                )
                self._enqueue_message({
                    "type": "error",
                    "text": f"[OpenCode error: HTTP {resp.status_code}]",
                })
                return

            logger.info("POST accepted, reading ndjson completion stream...")

            # 读取 ndjson 行（完成信号）
            for line in resp.iter_lines(decode_unicode=True):
                if line is None or line.strip() == "":
                    continue
                try:
                    data = json.loads(line)
                    # Check for error in ndjson response
                    if data.get("type") == "error":
                        error_msg = data.get("message", "未知错误")
                        logger.error(f"ndjson error: {error_msg}")
                        self._enqueue_message({
                            "type": "error",
                            "text": f"[OpenCode error: {error_msg}]",
                        })
                    else:
                        # 正常完成 — SSE 流已处理增量
                        logger.info("ndjson completion received")
                except json.JSONDecodeError:
                    logger.debug(f"ndjson non-JSON line: {line[:200]}")

        except requests.ConnectionError:
            logger.error("connection to OpenCode lost during POST")
            self._connected = False
            self._enqueue_message({
                "type": "error",
                "text": "[Connection to OpenCode lost]",
            })
        except requests.Timeout:
            logger.error("OpenCode POST request timed out")
            self._enqueue_message({
                "type": "error",
                "text": "[OpenCode request timed out]",
            })
        except Exception as e:
            logger.error(f"POST error: {e}")
            self._enqueue_message({
                "type": "error",
                "text": f"[POST error: {e}]",
            })

    # ------------------------------------------------------------------
    # 消息队列辅助方法
    # ------------------------------------------------------------------

    def _enqueue_message(self, msg):
        """线程安全地将消息入队，供主线程处理。"""
        with self._queue_lock:
            self._msg_queue.append(msg)

    def _dispatch_message(self, msg):
        """在主线程上分发排队的消息。

        消息类型：
            start    — 新的助手消息流式传输开始
            delta    — 增量文本块（逐 token）
            complete — 消息的完整累积文本
            end      — 流式传输结束
            tool_call — AI 调用了工具
            error    — 发生错误
        """
        msg_type = msg.get("type", "")

        if msg_type == "start":
            logger.info("streaming started")
            if self._chat_start_callback:
                self._chat_start_callback()

        elif msg_type == "delta":
            delta = msg.get("delta", "")
            if delta:
                logger.debug(f"delta: {delta[:80]}")
                if self._chat_delta_callback:
                    self._chat_delta_callback(delta)

        elif msg_type == "complete":
            text = msg.get("text", "")
            if text:
                logger.info(f"message reply: {text[:200]}")
                # 仅在未设置流式回调时使用旧版回调
                if self._chat_callback and not self._chat_start_callback:
                    self._chat_callback(text, self._session_id)

        elif msg_type == "end":
            logger.info("streaming ended")
            if self._chat_end_callback:
                self._chat_end_callback()

        elif msg_type == "tool_call":
            tool_name = msg.get("tool_name", "unknown")
            logger.info(f"tool invoked: {tool_name}")

        elif msg_type == "error":
            error_text = msg.get("text", "[Unknown error]")
            logger.error(f"error: {error_text}")
            if self._chat_callback:
                self._chat_callback(error_text, self._session_id)

        else:
            logger.warning(f"unknown message type: {msg_type}")
