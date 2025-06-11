from dataclasses import dataclass
from langgraph.graph.state import CompiledStateGraph

from src.model.schema import AgentInfo
from src.model.agents.mRNA_research import mRNA_research
from src.model.agents.patient_case_mrna_research import patient_case_mRNA_research
from src.model.agents.pMHC_affinity_prediction_research import pMHC_affinity_prediction_research
from src.model.agents.neo_antigen_research import neo_antigen_research  

DEFAULT_AGENT = "mRNA_research"
PMHC_AFFINITY_PREDICTION="pMHC_affinity_prediction"
PATIENT_CASE_MRNA_AGENT="patient_case_mRNA_research"
NEO_ANTIGEN="neo_antigen_research"

@dataclass
class Agent:
    description: str
    graph: CompiledStateGraph


agents: dict[str, Agent] = {
    "mRNA_research": Agent(
        description="Agent for predicting mRNA antigens.",
        graph=mRNA_research
    ),

    "pMHC_affinity_prediction": Agent(
        description="肽段亲和力预测agent.",
        graph=pMHC_affinity_prediction_research
    ),

    "patient_case_mRNA_research": Agent(
        description="研究患者案例 mRNA的Agent",
        graph=patient_case_mRNA_research
    ),

    "neo_antigen_research": Agent(
        description="完成个体化neo-antigen筛选的Agent",
        graph=neo_antigen_research
    ),
}

def get_agent(agent_id: str) -> CompiledStateGraph:
    return agents[agent_id].graph

def get_all_agents() -> dict:
    return [
        agent for agent_id, agent in agents.items()
    ]

def get_all_agent_info() -> list[AgentInfo]:
    return [
        AgentInfo(key=agent_id, description=agent.description) for agent_id, agent in agents.items()
    ]
