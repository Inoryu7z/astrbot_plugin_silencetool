### v1.0.0

**🔇 首次发布：工具调用时静默中间文本**

* 在非流式模式下，当 LLM 调用工具时自动抑制其生成的中间文本（如"好，我马上查询"），只保留工具调用完成后的最终结果消息。
* 支持群聊/私聊独立开关。
* 使用 `@on_decorating_result` 钩子 + `_ACTIVE_AGENT_RUNNERS` 内部字典 + `final_llm_resp` 状态判断实现精确拦截。

**⚠️ 已知限制**

* 仅在非流式输出模式下生效。流式模式下中间文本通过 streaming delta 直接发送，无钩子可拦截。
* 依赖 AstrBot 内部 API `_ACTIVE_AGENT_RUNNERS`，未来版本可能需要适配。
