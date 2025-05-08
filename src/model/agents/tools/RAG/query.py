import json
import logging
import os
import requests


from pathlib import Path
from langchain_core.tools import tool
from typing import Optional

from src.model.agents.tools.RAG.query_llm import query_llm
from src.utils.log import logger
current_file = Path(__file__).resolve()
current_script_dir = current_file.parent
project_root = current_file.parents[4] 
from config import CONFIG_YAML
from src.utils.log import logger

#理论和案例lightrag服务地址
theory_server_url: str = CONFIG_YAML["RAG"]["theory_server_url"]
case_server_url: str = CONFIG_YAML["RAG"]["case_server_url"]

folder_path = CONFIG_YAML["RAG"]["files_path"]

def run_rag_stream(
    query: str,
    server_url: str,
    mode: str = "mix",
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


# @tool
# def RAG_Expanded(
#     query: str,
# ) -> str:
#     """
#     使用LightRAG系统查询本地专业文献知识库，检索返回可参考信息。

#     Args:
#         query (str): 用户输入的问题
#     Returns:
#         str: JSON格式的响应（含 type + content）
#     """
#     mode = "mix"
#     top_k = 1
#     response_type = "string"
    
#     # 生成扩展查询
#     theory_query, case_query = expand_query(query)
#     logger.info(f"theory_query：{theory_query} \n case_query：{case_query}")

#     theory_response = run_rag_stream(
#         query=theory_query,
#         mode=mode,
#         top_k=top_k,
#         response_type=response_type
#     )
    
#     case_response = run_rag_stream(
#         query=case_query,
#         mode=mode,
#         top_k=top_k,
#         response_type=response_type
#     )
    
#     return json.dumps(
#         {
#             "type": "text",
#             "content": (
#                 "# 病例理论及方法相关\n"
#                 f"```\n{theory_response}\n```\n\n"
#                 "# 案例相关\n"
#                 f"```\n{case_response}\n```"
#             )
#         },
#         ensure_ascii=False
#     )
def process_files_from_response(response_content: str) -> str:
    """
    处理从 RAG Server 返回的字符串内容，查找文件夹中的匹配文件
    """
    # 按逗号分割字符串
    pmids = response_content.split(",")
    # 初始化最终结果字符串
    final_result = ""

    # 遍历每个 PMID
    for i, pmid in enumerate(pmids, start=1):
        # 初始化当前论文及其附件的字符串
        current_case = ""

        # 标记是否找到论文
        found_paper = False

        # 遍历文件夹中的文件
        for filename in os.listdir(folder_path):
            if pmid in filename:
                # 如果文件名完全匹配 PMID + ".md"，则认为是论文
                if filename == f"{pmid}.md":
                    found_paper = True
                    current_case += f"............第{i}个案例论文............n"
                    file_path = os.path.join(folder_path, filename)
                    with open(file_path, "r", encoding="utf-8") as file:
                        current_case += file.read() + "\n"
                    break  # 找到论文后退出循环

        # 如果找到论文，再查找附件
        if found_paper:
            attachment_count = 1  # 初始化附件计数器
            for filename in os.listdir(folder_path):
                if pmid in filename and filename != f"{pmid}.md":
                    current_case += f"............第{i}个论文的第{attachment_count}个附件............\n"
                    file_path = os.path.join(folder_path, filename)
                    with open(file_path, "r", encoding="utf-8") as file:
                        current_case += file.read() + "\n"
                    attachment_count += 1  # 附件计数器加 1

        # 将当前论文及其附件的内容添加到最终结果字符串中
        final_result += current_case + "\n"

    return final_result


@tool
def RAG(
    query: str,
    origin_query: str,
    files: str
) -> str:
    """
    使用LightRAG系统查询本地专业文献知识库，检索返回可参考信息。

    Args:
        query (str): 从可包含用户的输入和提示词中提取有用信息，用来rag检索的query。
        origin_query(str): 用户的原始输入，不包含任何修饰或修改。
        files:用户上传的文件的相关信息。（这部分信息有系统提供，无需模型提取）
    Returns:
        str: JSON格式的响应（含 type + content）
    """
    mode = "mix"
    top_k = 1
    response_type = "string"
    
    theory_response = run_rag_stream(
        query=query,
        mode=mode,
        top_k=top_k,
        response_type=response_type,
        server_url=theory_server_url
    )

    case_response_pmids = run_rag_stream(
        query=query,
        mode=mode,
        top_k=top_k,
        response_type=response_type,
        server_url=case_server_url
    )
    # 如果响应内容为空，直接返回
    if not case_response_pmids:
        
        case_response="没有检索到相应案例论文"
    else:
        # 处理响应内容并保存到文件
        case_response = process_files_from_response(case_response_pmids)

    rag_response = f"""
    -----检索到的相关理论片段-----
    {theory_response if theory_response else "没有检索到相关理论信息"}

    -----检索到的案例论文-----
    {case_response}
    """.strip()
   
    content=query_llm(origin_query, rag_response, files)


    return json.dumps(
        {
            "type": "text",
            "content": content
        },
        ensure_ascii=False
    )

if __name__ == "__main__":
    print(run_rag_stream("请根据知识图谱解释一下 Tumor-specific neo-antigens", mode="mix", top_k=1))