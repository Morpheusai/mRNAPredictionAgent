import aiohttp
import asyncio
import json
import traceback

from langchain_core.tools import tool

from config import CONFIG_YAML

netctlpan_url = CONFIG_YAML["TOOL"]["NETCTLPAN"]["url"]

@tool
async def NetCTLpan(input_file: str, mhc_allele: str = "HLA-A02:01", weight_of_clevage: float = 0.225,
              weight_of_tap: float = 0.025, peptide_length: str = "8,9,10,11") -> str:
    """
    使用NetCTLpan工具预测肽段序列与指定MHC分子的结合亲和力，用于筛选潜在的免疫原性肽段。
    该函数结合蛋白质裂解、TAP转运和MHC结合的预测，适用于疫苗设计和免疫研究。

    :param input_file: 输入的FASTA格式肽段序列文件路径
    :param mhc_allele: 用于比对的MHC等位基因名称，默认为"HLA-A02:01"
    :param weight_of_clevage: 蛋白质裂解预测的权重，默认为0.225
    :param weight_of_tap: TAP转运效率预测的权重，默认为0.025
    :param peptide_length: 预测的肽段长度范围，默认为"9"
    :return: 返回预测结果字符串，包含高亲和力肽段信息
    """
    
    payload = {
        "input_file": input_file,
        "mhc_allele": mhc_allele,
        "weight_of_clevage": weight_of_clevage,
        "weight_of_tap": weight_of_tap,
        "peptide_length": peptide_length
    }

    timeout = aiohttp.ClientTimeout(total=60)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(netctlpan_url, json=payload) as response:
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
    async def test():
        result = await NetCTLpan.ainvoke({
"input_file":"minio://molly/2ad83c64-0440-4d70-80bf-8a0054c0ecac_B0702.fsa", "peptide_length":"9"

        })
        print("NetCTLpan 异步调用结果：")
        print(result)

    asyncio.run(test())




