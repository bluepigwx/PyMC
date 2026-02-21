"""消息构建工具：统一构建客户端与服务端之间的标准消息格式。"""


def build_request(cmd, params=None):
    """构建客户端→服务端的请求消息。

    Args:
        cmd: 命令名称。
        params: 命令参数。

    Returns:
        格式化的消息字典: {"cmd": "xxx", "params": {...}}
    """
    return {"cmd": cmd, "params": params or {}}


def build_response(cmd, status, params=None):
    """构建客户端→服务端的响应消息。

    Args:
        cmd: 命令名称。
        status: 状态码，"ok" 或 "error"。
        params: 响应参数。

    Returns:
        格式化的消息字典: {"cmd": "xxx", "status": "ok|error", "params": {...}}
    """
    return {"cmd": cmd, "status": status, "params": params or {}}
