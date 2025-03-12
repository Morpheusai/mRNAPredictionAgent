from dataclasses import dataclass
from langgraph.graph.state import CompiledStateGraph

from src.model.schema import AgentInfo

DEFAULT_AGENT = "mRNA_research"


@dataclass
class Agent:
    description: str
    graph: CompiledStateGraph


agents: dict[str, Agent] = {}
async def initialize_agents():
    from src.model.agents.mRNA_research import compile_mRNA_research
    mRNA_research, conn = await compile_mRNA_research()
    agents["mRNA_research"] = Agent(
        description="A mRNA_research with web search and calculator.",
        graph=mRNA_research
    )
    return conn

def get_agent(agent_id: str) -> CompiledStateGraph:
    return agents[agent_id].graph


def get_all_agent_info() -> list[AgentInfo]:
    return [
        AgentInfo(key=agent_id, description=agent.description) for agent_id, agent in agents.items()
    ]
