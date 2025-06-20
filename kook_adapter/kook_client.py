import asyncio
import websockets
import json
import logging
import aiohttp
import zlib

class KookClient:
    def __init__(self, token, event_callback):
        self.token = token
        self.event_callback = event_callback  # 回调函数，用于处理接收到的事件
        self.ws = None
        self.running = False

    async def get_gateway_url(self):
        url = "https://www.kookapp.cn/api/v3/gateway/index"
        headers = {
            "Authorization": f"Bot {self.token}"
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                data = await resp.json()
                logging.info(f"[KOOK] 获取 gateway url: {data['data']['url']}")
                return data["data"]["url"]

    async def connect(self):
        gateway_url = await self.get_gateway_url()
        self.ws = await websockets.connect(gateway_url)
        self.running = True
        logging.info('[KOOK] WebSocket 连接成功')
        await self.listen()

    async def listen(self):
        try:
            while self.running:
                msg = await self.ws.recv()
                if isinstance(msg, bytes):
                    try:
                        msg = zlib.decompress(msg)
                    except Exception as e:
                        logging.error(f"[KOOK] 解压消息失败: {e}")
                        continue
                    msg = msg.decode('utf-8')
                logging.info(f"[KOOK] 收到原始消息: {msg}")
                data = json.loads(msg)
                await self.event_callback(data)
        except Exception as e:
            logging.error(f'[KOOK] WebSocket 监听异常: {e}')
            self.running = False

    async def send_text(self, channel_id, content):
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
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                result = await resp.text()
                logging.info(f"[KOOK] 发送文本消息响应: {result}")

    async def send_image(self, channel_id, image_url):
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
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                result = await resp.text()
                logging.info(f"[KOOK] 发送图片消息响应: {result}")

    async def close(self):
        self.running = False
        if self.ws:
            await self.ws.close() 