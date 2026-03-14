import socket
import logging
import threading
import json
from collections  import deque
import copy

logger = logging.getLogger(__name__)


_host = "localhost"
_port = 9987

class Plugin:
    def __init__(self, world, controller):
        self.socket = None
        
        self.recv_queue = deque()
        self.process_queue = deque()
        
        self._cmd_locker = threading.Lock()
        
        self.world = world
        self.controller = controller
        
        self.enable = False
        
    
    def init(self):
        """
        Docstring for init
        外部init接口
        :param self: Description
        """
        if not self.enable:
            return
        
        if self.socket != None:
            logger.warning(f"socket not none")
            self.socket.close()
        
        try:
            logger.info(f"try to connect {_host}:{_port}...")
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((_host, _port))
        except Exception as e:
            logger.error(f"failed to connect to {_host}:{_port} {e}")
            self.socket = None
            return
        
        logger.info(f"connect to {_host}:{_port} success")
        
        #开启收包线程
        try:
            self.recv_thread = threading.Thread(target=self._receiv)
            self.recv_thread.daemon = True
            self.recv_thread.start()
        except Exception as e:
            logger.error(f"create thread failed {e}")
            self.socket.close()
            raise Exception(e)
            
        logger.info(f"create receiv threading success")
            
            
        
    def _receiv(self):
        self.socket.settimeout(None)

        buffer = b''
        try:
            while True:
                data = self.socket.recv(8192)
                if not data:
                    logger.info("Server disconnected (recv returned empty)")
                    break
                buffer += data

                # Handle newline-delimited JSON or single JSON objects.
                # Try to decode complete JSON messages from the buffer.
                while buffer:
                    buffer = buffer.lstrip()
                    if not buffer:
                        break
                    try:
                        text = buffer.decode("utf-8")
                        decoder = json.JSONDecoder()
                        command, end_idx = decoder.raw_decode(text)
                        # Successfully parsed one JSON object
                        with self._cmd_locker:
                            self.recv_queue.append(command)
                        # Advance buffer past the consumed bytes
                        buffer = text[end_idx:].encode("utf-8")
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        # Incomplete message, wait for more data
                        break

        except ConnectionResetError:
            logger.warning("Server connection reset")
        except OSError as e:
            logger.error(f"Socket error in _receiv: {e}")
        
        
        
    def finit(self):
        if not self.enable:
            return
        
        if self.socket != None:
            try:
                self.socket.close()
            except Exception as e:
                logger.error(f"failed to disconnect {e}")
            finally:
                self.socket = None
                
    
    
    def update(self):
        """
        从recv_queue队列中取出操作在主线程中执行
        """
        if not self.enable:
            return
        
        if not self.socket:
            return
        
        with self._cmd_locker:
            # Swap queues
            tmp = self.recv_queue
            self.recv_queue = self.process_queue
            self.process_queue = tmp

        while self.process_queue:
            cmd = self.process_queue.popleft()
            logger.info(f"process cmd {cmd}")
            self.process_cmd(cmd)
                
    
    
    def _handle_hello(self, params):
        logger.info(f"handle hello message {params}")
        
    
    
    def _handle_get_scene_info(self, params={}):
        logger.info(f"_handle_get_scene_info")
        
        scene_info = {
            "camera" : {},
            "blocks" : [],
        }
        
        camerainfo = scene_info.get("camera")
        camerainfo["pos"] = list(self.controller._position)
        camerainfo["forward"] = list(self.controller._forward)
        camerainfo["up"] = list(self.controller._up)
        camerainfo["right"] = list(self.controller._right)
        
        scene_info["blocks"] = self.world.get_all_blocks()
        
        #logger.debug(f"get scene info :{scene_info}")
        return scene_info
    
    
    
    def _handle_set_blocks(self, params):
        logger.info(f"_handle_set_block params: {params}")
        
        for block in params["blocks"]:
            block_type = block["type"]
            wx = block["wx"]
            wy = block["wy"]
            wz = block["wz"]
            
            self.world.set_block((wx, wy, wz), block_type)
            
        return "ok"


    def _expand_regions(self, regions):
        """Expand region definitions into a flat list of (type, wx, wy, wz) tuples.

        Each region defines a rectangular volume with optional exclusions and overrides.

        Region format:
            {
                "type": int,           # block type for this region
                "x": [min, max],       # x range inclusive
                "y": [min, max],       # y range inclusive
                "z": [min, max],       # z range inclusive
                "exclude": [           # optional: positions to skip
                    {"x": int, "y": int, "z": int}, ...
                ],
                "override": [          # optional: positions with different block type
                    {"type": int, "x": int, "y": int, "z": int}, ...
                ]
            }

        Returns:
            list of (block_type, wx, wy, wz) tuples
        """
        _REQUIRED_KEYS = {"type", "x", "y", "z"}
        blocks = []
        for i, region in enumerate(regions):
            missing = _REQUIRED_KEYS - region.keys()
            if missing:
                logger.error(f"region[{i}] missing required keys: {sorted(missing)}, skipping")
                continue
            for axis in ("x", "y", "z"):
                val = region[axis]
                if not isinstance(val, list) or len(val) != 2:
                    logger.error(f"region[{i}].{axis} must be a [min, max] list, skipping")
                    continue

            block_type = region["type"]
            x_range = region["x"]
            y_range = region["y"]
            z_range = region["z"]

            # Build exclude set for O(1) lookup
            exclude_set = set()
            for ex in region.get("exclude", []):
                exclude_set.add((ex["x"], ex["y"], ex["z"]))

            # Build override map: (x, y, z) -> type
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


    def _handle_set_blocks_region(self, params):
        """Handle region-based block placement.

        Params format:
            {
                "regions": [
                    {
                        "type": 5,
                        "x": [0, 6], "y": [0, 0], "z": [0, 6],
                        "exclude": [{"x":3,"y":1,"z":0}, ...],
                        "override": [{"type":20,"x":0,"y":2,"z":3}, ...]
                    },
                    ...
                ]
            }
        """
        regions = params.get("regions", [])
        if not regions:
            logger.warning("set_blocks_region: empty regions")
            return "error: empty regions"

        blocks = self._expand_regions(regions)
        logger.info(f"set_blocks_region: {len(regions)} regions -> {len(blocks)} blocks")

        for block_type, wx, wy, wz in blocks:
            self.world.set_block((wx, wy, wz), block_type)

        return f"ok: placed {len(blocks)} blocks"
        
    
    
    def process_cmd(self, command):
        hadlers = {
            "hello" : self._handle_hello,
            "get_scene_info": self._handle_get_scene_info,
            "set_blocks": self._handle_set_blocks,
            "set_blocks_region": self._handle_set_blocks_region,
        }
        
        if not self.socket:
            logger.error(f"no valible socket to use")
            return
        
        cmd_type = command.get("cmd")
        cmd_params = command.get("params", {})
        request_id = command.get("request_id", "")

        handler = hadlers.get(cmd_type)
        if handler:
            try:
                result = handler(cmd_params)
                response = {
                    "cmd": cmd_type,
                    "status": "ok",
                    "request_id": request_id,
                    "params": result if isinstance(result, dict) else {"message": str(result)},
                }
            except Exception as e:
                logger.error(f"handler error for cmd '{cmd_type}': {e}")
                response = {
                    "cmd": cmd_type,
                    "status": "error",
                    "request_id": request_id,
                    "params": {"reason": str(e)},
                }
            try:
                response_json = json.dumps(response)
                self.socket.sendall(response_json.encode("utf-8"))
            except Exception as e:
                logger.error(f"send response error: {e}")
        else:
            logger.error(f"unknown command '{cmd_type}'")
            error_response = {
                "cmd": cmd_type,
                "status": "error",
                "request_id": request_id,
                "params": {"reason": f"unknown command: {cmd_type}"},
            }
            try:
                self.socket.sendall(json.dumps(error_response).encode("utf-8"))
            except Exception as e:
                logger.error(f"send error response failed: {e}")
            
    
    