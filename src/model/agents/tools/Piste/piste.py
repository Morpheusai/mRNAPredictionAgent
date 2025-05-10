import json
import aiohttp
import asyncio
import sys
import traceback

from langchain_core.tools import tool
from pathlib import Path
from typing import Optional

current_file = Path(__file__).resolve()
project_root = current_file.parents[5]                
sys.path.append(str(project_root))
from config import CONFIG_YAML

piste_url = CONFIG_YAML["TOOL"]["PISTE"]["url"]

@tool
async def PISTE(
    input_file_path: str,
    model_name: Optional[str] = None,
    threshold: Optional[float] = None,
    antigen_type: Optional[str] = None
) -> str:
    """
    调用远程 PISTE 服务（支持异步），输入为 MinIO 路径和参数选项。

    Args:
        input_file_path (str): MinIO 输入路径，例如 minio://bucket/file.csv
        model_name (str, optional): 模型名称，如 "random"、"unipep"、"reftcr"
        threshold (float, optional): binder 阈值（0-1）
        antigen_type (str, optional): 抗原类型，"MT" 或 "WT"

    Returns:
        str: JSON 格式预测结果
    """
    try:
        
        payload = {"input_file_dir_minio": input_file_path}
        if model_name:
            payload["model_name"] = model_name
        if threshold is not None:
            payload["threshold"] = threshold
        if antigen_type:
            payload["antigen_type"] = antigen_type

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(piste_url, json=payload) as response:
                response.raise_for_status()
                return await response.text()

    except Exception as e:
        print("发生异常类型：", type(e).__name__)
        print("异常信息：", str(e))
        traceback.print_exc()
        return json.dumps({
            "type": "text",
            "content": f"调用远程 PISTE 服务失败: {type(e).__name__} - {str(e)}"
        }, ensure_ascii=False)

#  测试入口（本地运行）
if __name__ == "__main__":
    test_input_path = "minio://molly/39e012fc-a8ed-4ee4-8a3b-092664d72862_piste_example.csv"

    async def test():
        result = await PISTE.ainvoke({
            "input_file_path": test_input_path,
            "model_name": "unipep",
            "threshold": 0.5,
            "antigen_type": "MT"
        })
        print("异步调用结果：")
        print(result)

    asyncio.run(test())

