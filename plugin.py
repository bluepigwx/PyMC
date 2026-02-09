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
        
        self._cmd_lokcer = threading.Lock()
        
        self.world = world
        self.controller = controller
        
    
    def init(self):
        """
        Docstring for init
        外部init接口
        :param self: Description
        """
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
                buffer += data
                
                try:
                    command = json.loads(buffer.decode("utf-8"))
                    with self._cmd_lokcer:
                        self.recv_queue.append(command)
                        
                    buffer = b''
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    pass
                
        except Exception as e:
            pass
        
        
    def finit(self):
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
        if not self.socket:
            return
        
        cnt = 0
        with self._cmd_lokcer:
            #交换
            tmp = self.recv_queue
            self.recv_queue = self.process_queue
            self.process_queue = tmp
            
        while self.process_queue:
            cmd = self.process_queue.popleft()    
            logger.info(f"process cmd {cmd}")
            self.process_cmd(cmd)
            cnt += 1
                
    
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
        
    
    
    def process_cmd(self, command):
        hadlers = {
            "hello" : self._handle_hello,
            "get_scene_info": self._handle_get_scene_info,
            "set_blocks": self._handle_set_blocks,
        }
        
        if not self.socket:
            logger.error(f"no valible socket to use")
            return
        
        cmd_type = command.get("type")
        cmd_params = command.get("params", {})
        
        handler = hadlers.get(cmd_type)
        if handler:
            try:
                result = handler(cmd_params)
                try:
                    response_json = json.dumps({"retcode":"success", "result":result})
                    self.socket.sendall(response_json.encode("utf-8"))
                except Exception as e:
                    logger.error(f"send data error {e}")
            except Exception as e:
                pass
        else:
            logger.error(f"unkonw command {cmd_type}")
            
    
    