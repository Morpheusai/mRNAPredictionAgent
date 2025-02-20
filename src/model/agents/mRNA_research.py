from datetime import datetime
from typing import Literal

from langchain_community.tools import DuckDuckGoSearchResults, OpenWeatherMapQueryRun
from langchain_community.utilities import OpenWeatherMapAPIWrapper
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda, RunnableSerializable
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.managed import RemainingSteps
from langgraph.prebuilt import ToolNode
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage


from src.model.agents.tools import mRNA
from src.model.agents.tools import NetMHCpan
from .core import get_model  # 相对导入




class AgentState(MessagesState, total=False):
    """`total=False` is PEP589 specs.

    documentation: https://typing.readthedocs.io/en/latest/spec/typeddict.html#totality
    """


tools = [mRNA,NetMHCpan]



current_date = datetime.now().strftime("%B %d, %Y")
instructions = f"""
    You are a helpful research assistant with the ability to search the web and use other tools.
    Today's date is {current_date}.

    NOTE: THE USER CAN'T SEE THE TOOL RESPONSE.

    A few things to remember:
    - Please include markdown-formatted links to any citations used in your response. Only include one
    or two citations per response unless more are needed. ONLY USE LINKS RETURNED BY THE TOOLS.
    - Use calculator tool with numexpr to answer math questions. The user does not understand numexpr,
      so for the final response, use human readable format - e.g. "300 * 200", not "(300 \\times 200)".
    """


def wrap_model(model: BaseChatModel) -> RunnableSerializable[AgentState, AIMessage]:
    model = model.bind_tools(tools)
    preprocessor = RunnableLambda(
        lambda state: [SystemMessage(content=instructions)] + state["messages"],
        name="StateModifier",
    )
    return preprocessor | model




async def acall_model(state: AgentState, config: RunnableConfig) -> AgentState:
    m = get_model(config["configurable"].get("model", None))
    model_runnable = wrap_model(m)
    response = await model_runnable.ainvoke(state, config)
    return {"messages": [response]}

##############################################################################
async def _parser(state: AgentState, config: RunnableConfig):
    messages = state["messages"]
    last_message = messages[-1]
    # print("333333333333333")
    # print(f"messages:{messages}")
    # print("33333333333333")    
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        # 处理所有工具调用
        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_call_id = tool_call["id"]
            tool_call_input=tool_call["args"].get("input_filename")

            # 检查是否已经存在相同 tool_call_id 的 ToolMessage
            if any(isinstance(msg, ToolMessage) and msg.tool_call_id == tool_call_id for msg in messages):
                continue  # 如果已经存在，跳过添加
            if tool_name == "NetMHCpan":
                input_filename = tool_call_input
                func_result = await NetMHCpan.ainvoke({"input_filename": input_filename})
                # logger.info(f"NetMHCpan result: {func_result}")
                # state["net_c4_result"] = func_result
                tool_msg = ToolMessage(
                    content=func_result,
                    tool_call_id=tool_call_id,
                )
                messages.append(tool_msg)
                
            elif tool_name == "mRNA":
                func_result = await mRNA.ainvoke({"input": "mRNA"})
                # logger.info(f"Neoantigen result: {func_result}")
                tool_msg = ToolMessage(
                    content=func_result,
                    tool_call_id=tool_call_id,
                )
                # messages.append(tool_msg)
                # print(f"mRNA:{tool_msg}")
                # print(f"messages:{messages}")
    return {"messages": [tool_msg]}

# Define the graph
agent = StateGraph(AgentState)
agent.add_node("model", acall_model)
agent.add_node("parserNode", _parser)
agent.set_entry_point("model")

agent.add_edge("parserNode", "model")

def pending_tool_calls(state: AgentState) -> Literal["tools", "done"]:
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        raise TypeError(f"Expected AIMessage, got {type(last_message)}")
    if last_message.tool_calls:
        return "tools"
    return "done"


agent.add_conditional_edges("model", pending_tool_calls, {"tools": "parserNode", "done": END})

# agent.add_edge("parserNode", END)

mRNA_research = agent.compile(checkpointer=MemorySaver())