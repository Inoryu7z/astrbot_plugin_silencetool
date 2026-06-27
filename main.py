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

    # 优先级定位：必须晚于 group_chat_plus(0) 等"需要读取中间文本"的装饰器，
    # 但早于 PostSplitter/ splitter(-1e17)、vits_pro(-100)、tts_plus(-1000) 等
    # "会发送或转换中间文本"的装饰器。
    # 原因：PostSplitter 会用 context.send_message 直接发送分段前缀（绕过本钩子），
    # 必须在它之前清空 result.chain，让它看到空链提前返回。但又必须在 group_chat_plus
    # 之后，因为 group_chat_plus 需要在 on_decorating_result 中读取链文本并累积到
    # _pending_bot_replies（供 agent 完成后统一保存历史），若先于它清空会破坏该累积逻辑。
    @filter.on_decorating_result(priority=-50)
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
            # Agent 仍在运行，这是中间文本，清空消息链以抑制发送。
            # 重要：不调用 event.stop_event()，否则会终止整个 Agent 循环。
            # 本钩子优先级 -50：晚于 group_chat_plus(0)（已读取并累积中间文本），
            # 早于 PostSplitter(-1e17) 等会直发分段前缀的装饰器，故清空后它们看到空链
            # 会提前返回，从而彻底避免中间文本泄漏，且不破坏 group_chat_plus 的历史累积。
            suppressed_len = sum(len(getattr(c, "text", "")) for c in result.chain)
            result.chain.clear()
            logger.info(
                f"[SilenceTool] 已抑制中间文本（agent 仍在多轮工具调用中，"
                f"被抑制内容约 {suppressed_len} 字符）"
            )
