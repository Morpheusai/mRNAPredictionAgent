import os
import sys
from typing import Annotated, TypedDict

from langchain_core.messages import ToolMessage
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
    # Custom keys for additional data can be added here such as - conversation_id: str

graph = StateGraph(GraphsState)

# Function to decide whether to continue tool usage or end the process
def should_continue(state: GraphsState, config: RunnableConfig):
    messages = state["messages"]
    logger.info(f"Messages: {messages}")
    last_message = messages[-1]
    if last_message.tool_calls[0]["name"] == "NetMHCpan":
        input_filename = config["configurable"]["input_filename"]
        func_result = NetMHCpan.invoke(                                                                                                                                  
            {             
                "input_filename": input_filename
            }             
        )
        toolMsg = ToolMessage(
            content = func_result,
            tool_call_id=last_message.tool_calls[0]["id"],
        )              
        return Command(
            update = {"messages": [toolMsg]},
            goto = END
        ) 
    return END  # End the conversation if no tool is needed

# Core invocation of the model
def _call_model(state: GraphsState):
    messages = state["messages"]
    llm = ChatOpenAI(
        model = LLM_MODEL,
        temperature = TEMPER,
        streaming=True,
    ).bind_tools(TOOLS)
    response = llm.invoke(messages)
    return {"messages": [response]}  # add the response to the messages using LangGraph reducer paradigm

# Define the structure (nodes and directional edges between nodes) of the graph
graph.add_edge(START, "modelNode")
graph.add_node("modelNode", _call_model)

# Add conditional logic to determine the next step based on the state (to continue or to end)
graph.add_conditional_edges(
    "modelNode",
    should_continue,  # This function will decide the flow of execution
)

# Compile the state graph into a runnable object
graph_runnable = graph.compile()

# Function to invoke the compiled graph externally
def invoke_our_graph(st_messages, config):
    # Ensure the callables parameter is a list as you can have multiple callbacks
    #if not isinstance(callables, list):
    #    raise TypeError("callables must be a list")
    # Invoke the graph with the current messages and callback configuration
    return graph_runnable.invoke(
        {
            "messages": st_messages
        }, 
        config = config,
        debug = False
    )