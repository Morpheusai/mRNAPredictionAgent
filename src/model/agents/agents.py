from dataclasses import dataclass
from langgraph.graph.state import CompiledStateGraph

from src.model.schema import AgentInfo

DEFAULT_AGENT = "mRNA_research"
DEMO_AGENT="demo_mRNA_research"


@dataclass
class Agent:
    description: str
    graph: CompiledStateGraph


agents: dict[str, Agent] = {}
async def initialize_agents():
    from src.model.agents.mRNA_research import compile_mRNA_research
    mRNA_research, conn = await compile_mRNA_research()
    agents["mRNA_research"] = Agent(
        description="Agent for predicting mRNA antigens.",
        graph=mRNA_research
    )

    from src.model.agents.DEMO_mRNA_research import demo_compile_mRNA_research
    DEMO_mRNA_research, DEMO_conn = await demo_compile_mRNA_research()
    agents["demo_mRNA_research"] = Agent(
        description="A demo of mRNA antigen agent.",
        graph=DEMO_mRNA_research
    )
    # 返回所有连接对象
    return {"mRNA_conn": conn, "demo_conn": DEMO_conn}

def get_agent(agent_id: str) -> CompiledStateGraph:
    return agents[agent_id].graph


def get_all_agent_info() -> list[AgentInfo]:
    return [
        AgentInfo(key=agent_id, description=agent.description) for agent_id, agent in agents.items()
    ]
