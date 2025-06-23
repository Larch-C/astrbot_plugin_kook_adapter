import asyncio
import websockets
import json
import logging
import aiohttp
import zlib
import time
import random

class KookClient:
    def __init__(self, token, event_callback):
        self.token = token
        self.event_callback = event_callback  # 回调函数，用于处理接收到的事件
        self.ws = None
        self.running = False
        self.session_id = None
        self.last_sn = 0  # 记录最后处理的消息序号
        self.heartbeat_task = None
        self.reconnect_delay = 1  # 重连延迟，指数退避
        self.max_reconnect_delay = 60  # 最大重连延迟
        self.heartbeat_interval = 30  # 心跳间隔
        self.heartbeat_timeout = 6  # 心跳超时时间
        self.last_heartbeat_time = 0
        self.heartbeat_failed_count = 0
        self.max_heartbeat_failures = 3  # 最大心跳失败次数

    async def get_gateway_url(self, resume=False, sn=0, session_id=None):
        """获取网关连接地址"""
        url = "https://www.kookapp.cn/api/v3/gateway/index"
        headers = {
            "Authorization": f"Bot {self.token}"
        }
        
        # 构建连接参数
        params = {}
        if resume:
            params['resume'] = 1
            params['sn'] = sn
            if session_id:
                params['session_id'] = session_id
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status != 200:
                        logging.error(f"[KOOK] 获取gateway失败，状态码: {resp.status}")
                        return None
                    
                    data = await resp.json()
                    if data.get('code') != 0:
                        logging.error(f"[KOOK] 获取gateway失败: {data}")
                        return None
                    
                    gateway_url = data["data"]["url"]
                    logging.info(f"[KOOK] 获取gateway成功: {gateway_url}")
                    return gateway_url
            except Exception as e:
                logging.error(f"[KOOK] 获取gateway异常: {e}")
                return None

    async def connect(self, resume=False):
        """连接WebSocket"""
        try:
            # 获取gateway地址
            gateway_url = await self.get_gateway_url(
                resume=resume, 
                sn=self.last_sn, 
                session_id=self.session_id
            )
            
            if not gateway_url:
                return False
            
            # 连接WebSocket
            self.ws = await websockets.connect(gateway_url)
            self.running = True
            logging.info('[KOOK] WebSocket 连接成功')
            
            # 启动心跳任务
            if self.heartbeat_task:
                self.heartbeat_task.cancel()
            self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            
            # 开始监听消息
            await self.listen()
            return True
            
        except Exception as e:
            logging.error(f'[KOOK] WebSocket 连接失败: {e}')
            return False

    async def listen(self):
        """监听WebSocket消息"""
        try:
            while self.running:
                try:
                    msg = await asyncio.wait_for(self.ws.recv(), timeout=10)
                    
                    if isinstance(msg, bytes):
                        try:
                            msg = zlib.decompress(msg)
                        except Exception as e:
                            logging.error(f"[KOOK] 解压消息失败: {e}")
                            continue
                        msg = msg.decode('utf-8')
                    
                    logging.debug(f"[KOOK] 收到原始消息: {msg}")
                    data = json.loads(msg)
                    
                    # 处理不同类型的信令
                    await self._handle_signal(data)
                    
                except asyncio.TimeoutError:
                    # 超时检查，继续循环
                    continue
                except websockets.exceptions.ConnectionClosed:
                    logging.warning("[KOOK] WebSocket连接已关闭")
                    break
                except Exception as e:
                    logging.error(f'[KOOK] 消息处理异常: {e}')
                    break
                    
        except Exception as e:
            logging.error(f'[KOOK] WebSocket 监听异常: {e}')
        finally:
            self.running = False

    async def _handle_signal(self, data):
        """处理不同类型的信令"""
        signal_type = data.get('s')
        
        if signal_type == 0:  # 事件消息
            # 更新消息序号
            if 'sn' in data:
                self.last_sn = data['sn']
            await self.event_callback(data)
            
        elif signal_type == 1:  # HELLO握手
            await self._handle_hello(data)
            
        elif signal_type == 3:  # PONG心跳响应
            await self._handle_pong(data)
            
        elif signal_type == 5:  # RECONNECT重连指令
            await self._handle_reconnect(data)
            
        elif signal_type == 6:  # RESUME ACK
            await self._handle_resume_ack(data)
            
        else:
            logging.debug(f"[KOOK] 未处理的信令类型: {signal_type}")

    async def _handle_hello(self, data):
        """处理HELLO握手"""
        hello_data = data.get('d', {})
        code = hello_data.get('code', 0)
        
        if code == 0:
            self.session_id = hello_data.get('session_id')
            logging.info(f"[KOOK] 握手成功，session_id: {self.session_id}")
            # 重置重连延迟
            self.reconnect_delay = 1
        else:
            logging.error(f"[KOOK] 握手失败，错误码: {code}")
            if code == 40103:  # token过期
                logging.error("[KOOK] Token已过期，需要重新获取")
            self.running = False

    async def _handle_pong(self, data):
        """处理PONG心跳响应"""
        self.last_heartbeat_time = time.time()
        self.heartbeat_failed_count = 0
        logging.debug("[KOOK] 收到心跳响应")

    async def _handle_reconnect(self, data):
        """处理重连指令"""
        logging.warning("[KOOK] 收到重连指令")
        # 清空本地状态
        self.last_sn = 0
        self.session_id = None
        self.running = False

    async def _handle_resume_ack(self, data):
        """处理RESUME确认"""
        resume_data = data.get('d', {})
        self.session_id = resume_data.get('session_id')
        logging.info(f"[KOOK] Resume成功，session_id: {self.session_id}")

    async def _heartbeat_loop(self):
        """心跳循环"""
        while self.running:
            try:
                # 随机化心跳间隔 (30±5秒)
                interval = self.heartbeat_interval + random.randint(-5, 5)
                await asyncio.sleep(interval)
                
                if not self.running:
                    break
                
                # 发送心跳
                await self._send_ping()
                
                # 等待PONG响应
                await asyncio.sleep(self.heartbeat_timeout)
                
                # 检查是否收到PONG响应
                if time.time() - self.last_heartbeat_time > self.heartbeat_timeout:
                    self.heartbeat_failed_count += 1
                    logging.warning(f"[KOOK] 心跳超时，失败次数: {self.heartbeat_failed_count}")
                    
                    if self.heartbeat_failed_count >= self.max_heartbeat_failures:
                        logging.error("[KOOK] 心跳失败次数过多，准备重连")
                        self.running = False
                        break
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                logging.error(f"[KOOK] 心跳异常: {e}")
                self.heartbeat_failed_count += 1

    async def _send_ping(self):
        """发送心跳PING"""
        try:
            ping_data = {
                "s": 2,
                "sn": self.last_sn
            }
            await self.ws.send(json.dumps(ping_data))
            logging.debug(f"[KOOK] 发送心跳，sn: {self.last_sn}")
        except Exception as e:
            logging.error(f"[KOOK] 发送心跳失败: {e}")

    async def reconnect(self):
        """重连方法"""
        logging.info(f"[KOOK] 开始重连，延迟: {self.reconnect_delay}秒")
        await asyncio.sleep(self.reconnect_delay)
        
        # 关闭当前连接
        await self.close()
        
        # 尝试重连
        success = await self.connect(resume=True)
        
        if success:
            # 重连成功，重置延迟
            self.reconnect_delay = 1
            logging.info("[KOOK] 重连成功")
        else:
            # 重连失败，增加延迟（指数退避）
            self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)
            logging.warning(f"[KOOK] 重连失败，下次延迟: {self.reconnect_delay}秒")
        
        return success

    async def send_text(self, channel_id, content):
        """发送文本消息"""
        url = "https://www.kookapp.cn/api/v3/message/create"
        headers = {
            "Authorization": f"Bot {self.token}",
            "Content-Type": "application/json"
        }
        payload = {
            "target_id": channel_id,
            "content": content,
            "type": 1
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get('code') == 0:
                            logging.info(f"[KOOK] 发送文本消息成功")
                        else:
                            logging.error(f"[KOOK] 发送文本消息失败: {result}")
                    else:
                        logging.error(f"[KOOK] 发送文本消息HTTP错误: {resp.status}")
        except Exception as e:
            logging.error(f"[KOOK] 发送文本消息异常: {e}")

    async def send_image(self, channel_id, image_url):
        """发送图片消息"""
        url = "https://www.kookapp.cn/api/v3/message/create"
        headers = {
            "Authorization": f"Bot {self.token}",
            "Content-Type": "application/json"
        }
        payload = {
            "target_id": channel_id,
            "content": image_url,
            "type": 2
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get('code') == 0:
                            logging.info(f"[KOOK] 发送图片消息成功")
                        else:
                            logging.error(f"[KOOK] 发送图片消息失败: {result}")
                    else:
                        logging.error(f"[KOOK] 发送图片消息HTTP错误: {resp.status}")
        except Exception as e:
            logging.error(f"[KOOK] 发送图片消息异常: {e}")

    async def close(self):
        """关闭连接"""
        self.running = False
        
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass
        
        if self.ws:
            try:
                await self.ws.close()
            except Exception as e:
                logging.error(f"[KOOK] 关闭WebSocket异常: {e}")
        
        logging.info("[KOOK] 连接已关闭") 