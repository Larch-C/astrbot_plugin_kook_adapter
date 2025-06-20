from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.platform import AstrBotMessage, PlatformMetadata
from astrbot.api.message_components import Plain, Image
from .kook_client import KookClient

class KookEvent(AstrMessageEvent):
    def __init__(self, message_str: str, message_obj: AstrBotMessage, platform_meta: PlatformMetadata, session_id: str, client: KookClient):
        super().__init__(message_str, message_obj, platform_meta, session_id)
        self.client = client
        self.channel_id = message_obj.group_id or message_obj.session_id

    async def send(self, message: MessageChain):
        for i in message.chain:
            if isinstance(i, Plain):
                await self.client.send_text(self.channel_id, i.text)
            elif isinstance(i, Image):
                await self.client.send_image(self.channel_id, i.file)
        await super().send(message) 