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

transphla_url = CONFIG_YAML["TOOL"]["TRANSPHLA"]["url"]
@tool
async def TransPHLA_AOMP(
    peptide_file: str,
    hla_file: str,
    threshold: float = 0.5,
    cut_length: int = 10,
    cut_peptide: bool = True
) -> str:
    """
    使用 TransPHLA_AOMP 工具预测肽段与 HLA 的结合能力，并自动返回结果文件链接。

    参数说明：
    - peptide_file: MinIO 中的肽段 FASTA 文件路径（如 minio://bucket/peptides.fasta）
    - hla_file: MinIO 中的 HLA FASTA 文件路径（如 minio://bucket/hlas.fasta）
    - threshold: 绑定预测阈值，默认 0.5
    - cut_length: 肽段最大切割长度
    - cut_peptide: 是否启用肽段切割处理

    返回：
    - JSON 字符串，包含 URL 及 markdown 格式的输出说明
    """
    
    payload = {
        "peptide_file": peptide_file,
        "hla_file": hla_file,
        "threshold": threshold,
        "cut_length": cut_length,
        "cut_peptide": cut_peptide
    }

    timeout = aiohttp.ClientTimeout(total=60)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(transphla_url, json=payload) as response:
                response.raise_for_status()
                return await response.json()
    except Exception as e:
        print("发生异常类型：", type(e).__name__)
        print("异常信息：", str(e))
        traceback.print_exc()

        return json.dumps({
            "type": "text",
            "content": f" TransPHLA工具运行失败: {type(e).__name__} - {str(e)}"
        }, ensure_ascii=False)

if __name__ == "__main__":
    async def test():
        result = await TransPHLA_AOMP.ainvoke({
            "peptide_file": "minio://molly/c2a3fc7e-acdb-483c-8ce4-3532ebb96136_peptides.fasta",
            "hla_file": "minio://molly/29959599-2e39-4a66-a22d-ccfb86dedd21_hlas.fasta",
            "threshold": 0.5,
            "cut_length": 10,
            "cut_peptide": True
        })
        print("TransPHLA 调用结果：")
        print(result)

    asyncio.run(test())
