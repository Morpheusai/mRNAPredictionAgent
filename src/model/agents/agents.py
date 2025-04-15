from dataclasses import dataclass
from langgraph.graph.state import CompiledStateGraph

from src.model.schema import AgentInfo

DEFAULT_AGENT = "mRNA_research"
PMHC_AFFINITY_PREDICTION="pMHC_affinity_prediction"
PATIENT_CASE_MRNA_AGENT="patient_case_mRNA_research"

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

    from model.agents.pMHC_affinity_prediction_research import compile_pMHC_affinity_prediction_research
    pMHC_affinity_prediction_research, pMHC_affinity_prediction_research_conn = await compile_pMHC_affinity_prediction_research()
    agents["pMHC_affinity_prediction"] = Agent(
        description="肽段亲和力预测agent.",
        graph=pMHC_affinity_prediction_research
    )

    from src.model.agents.patient_case_mrna_research import compile_patient_case_mRNA_research
    patient_case_mRNA_research, patient_case_mRNA_research_conn = await compile_patient_case_mRNA_research()
    agents["patient_case_mRNA_research"] = Agent(
        description="研究患者案例 mRNA 的Agent",
        graph=patient_case_mRNA_research
    )

    # 返回所有连接对象
    return {"mRNA_conn": conn, "pMHC_affinity_prediction_research_conn": pMHC_affinity_prediction_research_conn , "patient_case_mRNA_research_conn" :patient_case_mRNA_research_conn}

def get_agent(agent_id: str) -> CompiledStateGraph:
    return agents[agent_id].graph


def get_all_agent_info() -> list[AgentInfo]:
    return [
        AgentInfo(key=agent_id, description=agent.description) for agent_id, agent in agents.items()
    ]
