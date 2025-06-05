import aiohttp
import asyncio
import json
import sys
import traceback

from langchain_core.tools import tool
from pathlib import Path

current_file = Path(__file__).resolve()
project_root = current_file.parents[5]                
sys.path.append(str(project_root))
from config import CONFIG_YAML

nettcr_url = CONFIG_YAML["TOOL"]["NETTCR"]["url"]

@tool
async def NetTCR(input_file: str) -> str:
    """                                    
    NetTCR用于预测肽段（peptide）与 T 细胞受体（TCR）的相互作用。
    Args:                                  
        input_file (str): 输入文件的路径，文件需包含待预测的肽段和 TCR 序列。
    Returns:                               
        str: 返回高结合亲和力的肽段序例信息                                                                                                                           
    """
    
    payload = {
        "input_file": input_file
    }

    timeout = aiohttp.ClientTimeout(total=120)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(nettcr_url, json=payload) as response:
                response.raise_for_status()
                return await response.json()
    except Exception as e:
        print("发生异常类型：", type(e).__name__)
        print("异常信息：", str(e))
        traceback.print_exc()

        return json.dumps({
            "type": "text",
            "content": f"调用 NetMHCpan 服务失败: {type(e).__name__} - {str(e)}"
        }, ensure_ascii=False)
if __name__ == "__main__":
    # test_input = "minio://molly/8e2d5554-cd03-4088-98f4-1766952b4171_B0702.fsa"
    test_input = "minio://molly/a87cecf6-ed8d-4924-988f-38bfe095d112_small_example(1).csv"
    async def test():
        result = await NetTCR.ainvoke({
            "input_file": test_input,
        })
        print("NetTCR 异步调用结果：")
        print(result)

    asyncio.run(test())

