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

immuneapp_neo_url = CONFIG_YAML["TOOL"]["IMMUNEAPP_NEO"]["url"]

@tool
async def ImmuneApp_Neo(
    input_file: str,
    alleles: str = "HLA-A*01:01,HLA-A*02:01,HLA-A*03:01,HLA-B*07:02"
) -> str:
    """
    使用 ImmuneApp-Neo 工具预测 neoepitope 的免疫原性，仅支持 peplist 文件格式（.txt 或 .tsv）。

    参数:
    - input_file: MinIO 文件路径，例如 minio://bucket/file.txt
    - alleles: 逗号分隔的 HLA-I 等位基因列表

    返回:
    - JSON 格式字符串，包含结果链接或错误信息
    """
    
    payload = {
        "input_file": input_file,
        "alleles": alleles
    }

    timeout = aiohttp.ClientTimeout(total=60)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(immuneapp_neo_url, json=payload) as response:
                response.raise_for_status()
                return await response.text()
    except Exception as e:
        print("发生异常类型：", type(e).__name__)
        print("异常信息：", str(e))
        traceback.print_exc()

        return json.dumps({
            "type": "text",
            "content": f" ImmuneApp_Neo 执行失败: {type(e).__name__} - {str(e)}"
        }, ensure_ascii=False)
if __name__ == "__main__":
    async def test():
        result = await ImmuneApp_Neo.ainvoke({
            "input_file": "minio://molly/3a39b343-8e2e-4957-8256-55f9bdaae0a6_test_immunogenicity.txt",
            "alleles": "HLA-A*01:01,HLA-A*02:01,HLA-A*03:01,HLA-B*07:02"
        })
        print("ImmuneApp_Neo 调用结果：")
        print(result)

    asyncio.run(test())

