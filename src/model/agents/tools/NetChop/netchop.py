import json
import aiohttp
import sys
import traceback


from langchain_core.tools import tool
from pathlib import Path
from typing import Optional

current_file = Path(__file__).resolve()
project_root = current_file.parents[5]                
sys.path.append(str(project_root))
from config import CONFIG_YAML

netchop_url = CONFIG_YAML["TOOL"]["NETCHOP"]["url"]
@tool
async def NetChop(
    input_file: str,
    cleavage_site_threshold: Optional[float] = 0.5
) -> str:
    """
    自动调用远程 NetChop 工具进行蛋白质切割位点预测。

    参数说明：
    - input_file: MinIO 路径，例如 minio://bucket/path.fasta
    - cleavage_site_threshold: 切割阈值（默认 0.5，范围 0~1）

    返回：
    - str：NetChop 服务返回的 JSON 结果
    """
    
    payload = {
        "input_file": input_file,
        "cleavage_site_threshold": cleavage_site_threshold
    }

    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(netchop_url, json=payload) as response:
                response.raise_for_status()
                return await response.text()
    except Exception as e:
        print("发生异常类型：", type(e).__name__)
        print("异常信息：", str(e))
        traceback.print_exc()

        return json.dumps({
            "type": "text",
            "content": f"调用远程 NetChop 服务失败: {type(e).__name__} - {str(e)}"
        }, ensure_ascii=False)


if __name__ == "__main__":
    test_input = "minio://molly/ab58067f-162f-49af-9d42-a61c30d227df_test_netchop.fsa"

    import asyncio
    async def test():
        result = await NetChop.ainvoke({
            "input_file": test_input,
            "cleavage_site_threshold": 0.6
        })
        print("异步调用结果：")
        print(result)

    asyncio.run(test())

