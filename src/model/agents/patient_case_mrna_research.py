import aiosqlite

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda, RunnableSerializable
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, MessagesState, StateGraph
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage
from typing import Literal,Optional

from src.model.agents.tools import RAG_Expanded
from src.utils.log import logger

from .core import get_model  # 相对导入
from .core.patient_case_mrna_prompts import MRNA_AGENT_PROMPT

class AgentState(MessagesState, total=False):
    """`total=False` is PEP589 specs.
    documentation: https://typing.readthedocs.io/en/latest/spec/typeddict.html#totality
    """
    rag_result: Optional[str]=None

TOOLS = [RAG_Expanded]       


def wrap_model(model: BaseChatModel, system_prompt: str) -> RunnableSerializable[AgentState, AIMessage]:
    model = model.bind_tools(TOOLS)
    #导入prompt
    preprocessor = RunnableLambda(
        lambda state: [SystemMessage(content=system_prompt)] + state["messages"],
        name="StateModifier",
    )
    return preprocessor | model


async def modelNode(state: AgentState, config: RunnableConfig) -> AgentState:
    m = get_model(
        config["configurable"].get("model", None),
        config["configurable"].get("temperature", None),
        config["configurable"].get("max_tokens", None),
        config["configurable"].get("base_url", None),
        config["configurable"].get("frequency_penalty", None),
        )
    #添加文件到system token里面
    file_list = config["configurable"].get("file_list", None)
    # 处理文件列表
    patient_info = ""
    if file_list:
        for conversation_file in file_list:
            for file in conversation_file.files:
                file_name = file.file_name
                file_content = file.file_content
                file_desc = file.file_desc
                file_instructions = f"*上传文件名*: {file_name} \n" + \
                                    f"*上传的文件描述*: {file_desc} \n" + \
                                    f"*上传的文件内容*: {file_content} \n"
                patient_info += file_instructions
    references = state.get("rag_result", "暂无")
    system_prompt = MRNA_AGENT_PROMPT.format(
        patient_info = patient_info,
        references = references
    )
    logger.info(f"Current system prompt: {system_prompt}")
    model_runnable = wrap_model(m, system_prompt)
    response = await model_runnable.ainvoke(state, config)
    return {"messages": [response]}

async def should_continue(state: AgentState, config: RunnableConfig):
    messages = state["messages"]
    last_message = messages[-1]
    logger.info(f"Current last message: {last_message}")
    tmp_tool_msg = []
    rag_result=""
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        # 处理所有工具调用
        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_call_id = tool_call["id"]

            # 检查是否已经存在相同 tool_call_id 的 ToolMessage
            if any(isinstance(msg, ToolMessage) and msg.tool_call_id == tool_call_id for msg in messages):
                continue  # 如果已经存在，跳过添加
            if tool_name == "RAG_Expanded":
                query = tool_call["args"].get("query")
                func_result = await RAG_Expanded.ainvoke(
                    {
                        "query": query
                    }
                )
                rag_result = func_result
                logger.info(f"RAG_Expanded result: {func_result}")
                tool_msg = ToolMessage(
                    content=func_result,
                    tool_call_id=tool_call_id,
                )
                tmp_tool_msg.append(tool_msg)                
    return {
        "messages": tmp_tool_msg,
        "rag_result": rag_result
    }
# Define the graph
PatientCaseMrnaAgent = StateGraph(AgentState)
PatientCaseMrnaAgent.add_node("modelNode", modelNode)
PatientCaseMrnaAgent.add_node("should_continue", should_continue)
PatientCaseMrnaAgent.set_entry_point("modelNode")

PatientCaseMrnaAgent.add_edge("should_continue", "modelNode")

def pending_tool_calls(state: AgentState) -> Literal["tools", "done"]:
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        raise TypeError(f"Expected AIMessage, got {type(last_message)}")
    if last_message.tool_calls:
        return "tools"
    return "done"


PatientCaseMrnaAgent.add_conditional_edges("modelNode", pending_tool_calls, {"tools": "should_continue", "done": END})


async def compile_patient_case_mRNA_research():
    patient_case_mRNA_research_conn = await aiosqlite.connect("checkpoints.sqlite")
    patient_case_mRNA_research = PatientCaseMrnaAgent.compile(checkpointer=AsyncSqliteSaver(patient_case_mRNA_research_conn))
    return patient_case_mRNA_research, patient_case_mRNA_research_conn