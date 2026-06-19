from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

# 内部 API：记录当前活跃的 Agent Runner，用于判断 Agent 是否仍在运行
from astrbot.core.pipeline.process_stage.follow_up import _ACTIVE_AGENT_RUNNERS


@register(
    "astrbot_plugin_silencetool",
    "Inoryu7z",
    "工具调用时静默中间文本",
    "1.0.0",
)
class SilenceToolPlugin(Star):
    """在工具调用时抑制 LLM 的中间文本输出，避免消息轰炸。"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

    def _cfg(self, key: str, default=None):
        return self.config.get(key, default)

    @filter.on_decorating_result(priority=-10**18)
    async def on_decorating_result(self, event: AstrMessageEvent):
        """在消息发送前拦截，抑制工具调用过程中的中间文本。"""
        if not self._cfg("enable_silence", True):
            return

        if not self._cfg("enable_group_process", True):
            group_id = getattr(getattr(event, "message_obj", None), "group_id", None)
            if group_id:
                return

        result = event.get_result()
        if result is None or not result.chain:
            return

        # 仅处理 LLM 结果
        is_llm = False
        is_llm_result = getattr(result, "is_llm_result", None)
        if callable(is_llm_result):
            try:
                is_llm = bool(is_llm_result())
            except Exception:
                pass

        if not is_llm:
            content_type = getattr(result, "result_content_type", None)
            if content_type is not None:
                type_name = getattr(content_type, "name", "")
                is_llm = type_name in {"LLM_RESULT", "AGENT_RUNNER_RESULT"}

        if not is_llm:
            return

        # 获取当前活跃的 Agent Runner
        umo = getattr(event, "unified_msg_origin", None)
        if not umo:
            return

        runner = _ACTIVE_AGENT_RUNNERS.get(umo)
        if runner is None:
            return

        # final_llm_resp 为 None 说明 Agent 还未完成（有工具调用待执行）
        # 此时 yield 的 llm_result 是中间文本，需要抑制
        final_resp = None
        get_final = getattr(runner, "get_final_llm_resp", None)
        if callable(get_final):
            try:
                final_resp = get_final()
            except Exception:
                final_resp = getattr(runner, "final_llm_resp", None)
        else:
            final_resp = getattr(runner, "final_llm_resp", None)

        if final_resp is None:
            # Agent 仍在运行，这是中间文本，清空消息链以抑制发送
            # 重要：不调用 event.stop_event()，否则会终止整个 Agent 循环
            result.chain.clear()
            logger.debug("[SilenceTool] 已抑制工具调用前的中间文本")
