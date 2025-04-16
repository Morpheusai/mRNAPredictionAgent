import json
import requests
import logging

from pathlib import Path
from langchain_core.tools import tool
from typing import Optional

from src.model.agents.query_expansion_agent import expand_query
# current_file = Path(__file__).resolve()
# current_script_dir = current_file.parent
# project_root = current_file.parents[4] 
# from config import CONFIG_YAML
# from src.utils.log import logger
server_url: str = "http://localhost:60825/query/stream"
def run_rag_stream(
    query: str,
    mode: str = "hybrid",
    top_k: int = 1,
    only_need_context: bool = True,
    only_need_prompt: bool = False,
    response_type: str = "string",
    
) -> str:
    """
    调用 LightRAG Server 的流式接口，并实时返回拼接结果
    """

    payload = {
        "query": query,
        "mode": mode,
        "top_k": top_k,
        "only_need_context": only_need_context,
        "only_need_prompt": only_need_prompt,
        "response_type": response_type
    }

    try:
        response = requests.post(server_url, json=payload, stream=True)
        response.raise_for_status()

        result_content = ""
        # logger.info("📡 开始流式接收 RAG 响应：")
        for line in response.iter_lines(decode_unicode=True):
            if line.strip():
                data = json.loads(line)
                if "response" in data:
                    # print(data["response"], end="", flush=True)
                    result_content += data["response"]
                elif "error" in data:
                    # logger.error(f"错误: {data['error']}")
                    return  f"错误: {data['error']}"

        return result_content

    except Exception as e:
        # logger.error(f"调用 RAG Server 失败：{e}")
        return f"调用 RAG 工具失败：{e}"


@tool
def RAG_Expanded(
    query: str,
    mode: str = "mix",
    top_k: int = 1,
    response_type: str = "string"
) -> str:
    """
    使用 LightRAG Server 查询本地知识库，返回答案。

    Args:
        query (str): 用户输入的问题
        mode (str): 检索模式，支持 naive, local, hybrid, mix 等
        top_k (int): 返回前 K 条检索内容
        response_type (str): 响应格式，例如 string, bullet points 等

    Returns:
        str: JSON格式的响应（含 type + content）
    """
    
    # 生成扩展查询
    theory_query, case_query = expand_query(query)

    
    theory_response = run_rag_stream(
        query=theory_query,
        mode=mode,
        top_k=top_k,
        response_type=response_type
    )
    
    case_response = run_rag_stream(
        query=case_query,
        mode=mode,
        top_k=top_k,
        response_type=response_type
    )
    
    
    return json.dumps(
        {
            "type": "text",
            "content": f"\n# 病例理论及方法相关\n```{theory_response}```\n\n# 案例相关\n```{case_response}```"
        },
        ensure_ascii=False
    )

    
if __name__ == "__main__":
    print(run_rag_stream("请根据知识图谱解释一下 Tumor-specific neo-antigens", mode="mix", top_k=1))
    