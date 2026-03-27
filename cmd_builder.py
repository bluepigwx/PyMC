"""消息构建工具：统一构建客户端与服务端之间的标准消息格式。"""


def build_request(cmd, params=None):
    """构建客户端→服务端的请求消息。

    Args:
        cmd: 命令名称。
        params: 命令参数。

    Returns:
        格式化的消息字典: {"cmd": "xxx", "params": {...}}
    """
    p = params.copy() if params else {}
    p["session_id"] = "ses_2d680558fffessmUvMSvZpmC2R"
    return {"cmd": cmd, "params": p}


def build_response(cmd, status, params=None, request_id=None):
    """构建客户端→服务端的响应消息。

    Args:
        cmd: 命令名称。
        status: 状态码，"ok" 或 "error"。
        params: 响应参数。
        request_id: 请求唯一标识，服务端发来的原样回传。

    Returns:
        格式化的消息字典。
    """
    msg = {"cmd": cmd, "status": status, "params": params or {}}
    msg["params"]["session_id"] = "ses_2d680558fffessmUvMSvZpmC2R"
    if request_id:
        msg["request_id"] = request_id
    return msg
