import sys
from typing import Tuple
from pathlib import Path

from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate

from .core import get_model
from .core.patient_case_mrna_prompts import QUERY_EXPAND_SYSTEM_PROMPT  # 需要先在prompts.py添加
from src.model.schema.models import FileDescriptionName


# 构建提示模板
system_prompt = SystemMessagePromptTemplate.from_template(QUERY_EXPAND_SYSTEM_PROMPT)
human_prompt = HumanMessagePromptTemplate.from_template("原始查询：'''{query}'''")
chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

# ================= 模型配置 =================
query_expand_agent = get_model(
                FileDescriptionName.GPT_4O, FileDescriptionName.TEMPERATURE, 
                FileDescriptionName.MAX_TOKENS, FileDescriptionName.BASE_URL, 
                FileDescriptionName.FREQUENCY_PENALTY
                 )

# ================= 处理链 =================
query_expand_chain = chat_prompt | query_expand_agent

# ================= 业务逻辑 =================
def expand_query(query: str) -> Tuple[str, str]:
    """
    查询扩展主函数
    返回格式：(theory_query, case_query)
    """
    try:
        # 执行模型调用
        response = query_expand_chain.invoke({"query": query})
        
        # 解析响应内容
        if not response.content:
            raise ValueError("Empty response from LLM")
            
        content = response.content.strip()
        
        # 解析结果（增强容错处理）
        theory_part = content.split("Theoretical version:")[1].split("\n")[0].strip().strip("[]")
        case_part = content.split("Case version:")[1].split("\n")[0].strip().strip("[]")
        
        return theory_part, case_part
        
    except Exception as e:
        # 降级方案：返回带标识的原始查询
        return (
            f"{query}（请从理论角度分析）",
            f"{query}（请结合实际案例说明）"
        )
    
if __name__ == "__main__":
    print(expand_query("请根据知识图谱解释一下 Tumor-specific neo-antigens", mode="mix", top_k=1))
        