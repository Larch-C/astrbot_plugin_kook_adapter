from astrbot.api.star import Context, Star, register
@register("kook_adapter", "wuyan1003", "KOOK适配器", "0.0.2")
class KookAdapterPlugin(Star):
    def __init__(self, context: Context):
        from .kook_adapter.kook_adapter import KookPlatformAdapter # noqa 