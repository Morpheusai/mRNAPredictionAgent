import aiohttp
import asyncio
import json
import sys
import traceback

from langchain_core.tools import tool
from pathlib import Path
from typing import List, Optional

current_file = Path(__file__).resolve()
project_root = current_file.parents[5]                
sys.path.append(str(project_root))
from config import CONFIG_YAML

immuneapp_url = CONFIG_YAML["TOOL"]["IMMUNEAPP"]["url"]

@tool
async def ImmuneApp(
    input_file_dir: str,
    alleles: Optional[List[str]] = ["HLA-A*01:01", "HLA-A*02:01", "HLA-A*03:01", "HLA-B*07:02"],
    use_binding_score: bool = True,
    peptide_lengths: Optional[List[int]] = [8,9]
) -> str:
    """
    使用 ImmuneApp 工具预测抗原肽段与 MHC 的结合能力（自动识别输入格式）。

    参数：
    - input_file_dir: MinIO 路径（.txt 表示 peplist，.fa/.fasta 为 fasta 格式）
    - alleles: MHC 等位基因列表（如 ["HLA-A*01:01", "HLA-A*02:01"]）
    - use_binding_score: 是否使用绑定打分（-b 参数）
    - peptide_lengths: 仅用于 fasta 输入的肽段长度列表

    返回：
    - JSON 字符串，包含预测结果或错误信息
    """
    if isinstance(alleles, list):
        alleles = ",".join(alleles) 
    payload = {
        "input_file_dir": input_file_dir,
        "alleles": alleles,
        "use_binding_score": use_binding_score,
        "peptide_lengths": peptide_lengths
    }

    timeout = aiohttp.ClientTimeout(total=60)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(immuneapp_url, json=payload) as response:
                response.raise_for_status()
                return await response.json()
    except Exception as e:
        print("发生异常类型：", type(e).__name__)
        print("异常信息：", str(e))
        traceback.print_exc()

        return json.dumps({
            "type": "text",
            "content": f" ImmuneApp工具执行失败: {type(e).__name__} - {str(e)}"
        }, ensure_ascii=False)
        
if __name__ == "__main__":
    async def test():
        result = await ImmuneApp.ainvoke({
            "input_file_dir": "minio://molly/aeb1733e-d1d1-4279-bc94-43fc3eee6239_test_peplist.txt",
            "alleles": ["HLA-A*01:01", "HLA-A*02:01", "HLA-A*03:01", "HLA-B*07:02"],
            "use_binding_score": True,
            "peptide_lengths": [8, 9]
        })
        print("ImmuneApp 调用结果：")
        print(result)

    asyncio.run(test())
