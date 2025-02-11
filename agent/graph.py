import os
import sys
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import MemorySaver 
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import START, END, StateGraph
from langgraph.graph.message import AnyMessage, add_messages
from langchain_openai import ChatOpenAI
from langgraph.types import Command

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from config import CONFIG_YAML
from agent.tools import NetMHCpan
from utils.log import logger

# llm 
LLM_MODEL = CONFIG_YAML["LLM"]["model_name"]
TEMPER = CONFIG_YAML["LLM"]["temperature"]

# tools
TOOLS = [NetMHCpan]

# This is the default state same as "MessageState" TypedDict but allows us accessibility to custom keys
class GraphsState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    net_c4_result: str
    # Custom keys for additional data can be added here such as - conversation_id: str

graph = StateGraph(GraphsState)

# Function to decide whether to continue tool usage or end the process
def _parser(state: GraphsState, config: RunnableConfig):
    messages = state["messages"]
    logger.info(f"Should continue Messages: {messages}")
    last_message = messages[-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        if last_message.tool_calls[0]["name"] == "NetMHCpan":
            input_filename = config["configurable"]["input_filename"]
            func_result = NetMHCpan.invoke(
                {             
                    "input_filename": input_filename
                }             
            )
            logger.info(f"NetMHCpan fun result: {func_result}")
            state["net_c4_result"] = func_result
            toolMsg = ToolMessage(
                content = func_result,
                tool_call_id = last_message.tool_calls[0]["id"],
            )              
            state["messages"].append(toolMsg)
            #return Command(
            #    update = {"messages": [toolMsg]},
            #    goto = END
            #)
    return state  # End the conversation if no tool is needed

# Core invocation of the model
def _call_model(state: GraphsState, config: RunnableConfig):
    messages_invoke = state["messages"]
    input_filename = config["configurable"]["input_filename"]
    if input_filename:
        messages_invoke = [
            SystemMessage(
                content=f"The file path entered by the user is: \"{input_filename}\""
            )
        ] + messages_invoke
    logger.info(f"Call model Messages: {messages_invoke}")
    llm = ChatOpenAI(
        model = LLM_MODEL,
        temperature = TEMPER,
        streaming=True,
    ).bind_tools(TOOLS)
    response = llm.invoke(messages_invoke)
    return {"messages": [response]}  # add the response to the messages using LangGraph reducer paradigm

# Define the structure (nodes and directional edges between nodes) of the graph
graph.add_edge(START, "modelNode")
graph.add_node("modelNode", _call_model)
graph.add_node("parserNode", _parser)

# Add conditional logic to determine the next step based on the state (to continue or to end)
graph.add_edge("modelNode", "parserNode")
graph.add_edge("parserNode", END)

# Compile the state graph into a runnable object
GRAPH_MEMORY = MemorySaver()
GRAPH = graph.compile(
    checkpointer=GRAPH_MEMORY
)
