import sys

from pathlib import Path

from src.model.agents.tools.NeoMRNASelection.cds_combine import concatenate_peptides_with_linker
from src.model.agents.tools.NeoMRNASelection.utr_spacer_rnafold import utr_spacer_rnafold_to_mrna

current_file = Path(__file__).resolve()
project_root = current_file.parents[5]
sys.path.append(str(project_root))
from config import CONFIG_YAML

MARKDOWN_DOWNLOAD_URL_PREFIX = CONFIG_YAML["TOOL"]["COMMON"]["markdown_download_url_prefix"]

async def step5_mrna_design(
    mrna_input_file_path: str,
    writer,
    mrna_design_process_result: list
) -> dict:
    """
    第五步：mRNA疫苗设计
    
    Args:
        mrna_input_file_path: mRNA输入文件路径
        writer: 流式输出写入器
        mrna_design_process_result: 过程结果记录列表
    
    Returns:
        markdown链接的字符串
    """
    # 步骤开始描述
    STEP5_DESC1 = """
### 第5部分-mRNA疫苗设计
基于默认的裂解子对对上述肽段序列，完成cds区域的序列
"""
    writer(STEP5_DESC1)
    mrna_design_process_result.append(STEP5_DESC1)
    
    # 运行CDS组合工具
    cds_result = await concatenate_peptides_with_linker(mrna_input_file_path)
    
    if not cds_result:
        raise Exception("mRNA设计阶段CDS组合工具执行失败")
  
    STEP5_DESC2 = """
基于默认的裂解子对对上述肽段序列已完成密码子的生成，正在进行下一步mRNA设计。
"""
    writer(STEP5_DESC2)
    mrna_design_process_result.append(STEP5_DESC2)    

    # 运行UTR和RNAfold工具
    result = await utr_spacer_rnafold_to_mrna(cds_result)
    
    if not result or not isinstance(result, tuple):
        raise Exception(f"mRNA设计阶段UTR和RNAfold工具执行失败：{result}")
    
    utr_spacer_rnafold_result_url, utr_spacer_rnafold_result_content = result
    
    # 输出结果
    writer("## mRNA筛选流程结果已获取，下载链接如下，在excel表中肽段信息一列中：linear代表线性mRNA，circular代码环状mRNA：\n")
    
    # result_dict = {
    #     "type": "link",
    #     "url": utr_spacer_rnafold_result_url,
    #     "content": ""
    # }
    
    # writer(result_dict)
    
    # 提取链接信息
    rnafold_result_url = utr_spacer_rnafold_result_url['rnaflod_result_file_url']
    secondary_structure_urls = [
        v for k, v in utr_spacer_rnafold_result_url.items() 
        if k.startswith('sequence_')
    ]
    
    # 构建文件列表
    files = [{"name": "RNAFold_results.xlsx", "url": MARKDOWN_DOWNLOAD_URL_PREFIX+rnafold_result_url}]
    
    for i, url in enumerate(secondary_structure_urls, 1):
        if len(secondary_structure_urls) > 1:
            name = f"二级结构图_{i}.svg"
        else:
            name = "二级结构图.svg"
        files.append({"name": name, "url": MARKDOWN_DOWNLOAD_URL_PREFIX+url})
    
    # 生成Markdown链接
    markdown_link = "\n".join(
        f"- [{file['name']}]({file['url']})" 
        for file in files
    ) + "\n"
    writer(markdown_link)
    
    # 步骤完成描述
    STEP5_DESC3 = """
---

**说明**:  
• 上表显示肽段的最小自由能(MFE)二级结构预测结果  
• 括号表示法解析:  
- `(` / `)`: 配对的碱基对  
- `.`: 未配对碱基  
• 最后一列为自由能值（单位：kcal/mol）
"""
    mrna_design_process_result.append(STEP5_DESC3)
    
    return markdown_link