import imgui
import logging

logger = logging.getLogger(__name__)


class ChatBox:
    """聊天对话框：按 ` 键弹出，输入消息后回车发送。

    需要外部在渲染循环中调用 draw() 来绘制 imgui 窗口。
    """

    def __init__(self, agent_plugin):
        self._agent_plugin = agent_plugin
        self._visible = False
        self._input_text = ""
        self._chat_history = []  # [(role, text), ...]
        self._need_focus = False
        self._last_sent = ""  # 防止同一条消息重复发送

    def toggle(self):
        """切换对话框的显示/隐藏状态。"""
        self._visible = not self._visible
        if self._visible:
            self._need_focus = True

    @property
    def visible(self):
        return self._visible

    def on_chat_reply(self, reply, conversation_id):
        """收到 agent 回复时调用，将回复追加到聊天记录。

        Args:
            reply: agent 回复文本。
            conversation_id: 当前对话 ID。
        """
        self._chat_history.append(("agent", reply))
        self._last_sent = ""  # 重置，允许用户再次发送相同消息

    def draw(self):
        """在 imgui 帧中绘制聊天对话框。必须在 imgui.new_frame() 之后调用。"""
        if not self._visible:
            return

        # 窗口大小和位置
        io = imgui.get_io()
        win_width = 500
        win_height = 400
        imgui.set_next_window_size(win_width, win_height, imgui.FIRST_USE_EVER)
        imgui.set_next_window_position(
            io.display_size.x / 2 - win_width / 2,
            io.display_size.y / 2 - win_height / 2,
            imgui.FIRST_USE_EVER,
        )

        expanded, opened = imgui.begin("Chat", True)
        if not opened:
            self._visible = False
            imgui.end()
            return

        if expanded:
            # 聊天记录区域
            avail_height = imgui.get_content_region_available().y - 30
            imgui.begin_child("chat_history", 0, avail_height, border=True)
            for role, text in self._chat_history:
                if role == "user":
                    imgui.text_colored(f"You: {text}", 0.4, 0.8, 1.0)
                else:
                    imgui.text_wrapped(f"Agent: {text}")
            # 自动滚动到底部
            if imgui.get_scroll_y() >= imgui.get_scroll_max_y() - 20:
                imgui.set_scroll_here_y(1.0)
            imgui.end_child()

            # 输入框
            if self._need_focus:
                imgui.set_keyboard_focus_here()
                self._need_focus = False

            changed, self._input_text = imgui.input_text(
                "##chat_input",
                self._input_text,
                256,
                imgui.INPUT_TEXT_ENTER_RETURNS_TRUE,
            )

            imgui.same_line()
            send_clicked = imgui.button("Send")

            # 回车或点击 Send 统一触发，防止同帧重复
            if (changed or send_clicked) and self._input_text.strip():
                msg = self._input_text.strip()
                self._input_text = ""
                self._need_focus = True
                self._send_message(msg)

        imgui.end()

    def _send_message(self, text):
        """发送消息到 agent 服务端并记录到聊天历史。

        Args:
            text: 用户输入的消息文本。
        """
        # 防止连续帧重复发送同一条消息
        if text == self._last_sent:
            return
        self._last_sent = text

        logger.info(f"send chat: {text[:200]}")
        self._chat_history.append(("user", text))
        try:
            self._agent_plugin.send_chat(text)
        except Exception as e:
            logger.error(f"failed to send chat: {e}")
            self._chat_history.append(("agent", "[发送失败，请检查连接]"))
