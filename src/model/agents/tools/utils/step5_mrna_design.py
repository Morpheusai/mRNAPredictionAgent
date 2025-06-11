from src.model.agents.tools.NeoMRNASelection.cds_combine import concatenate_peptides_with_linker
from src.model.agents.tools.NeoMRNASelection.utr_spacer_rnafold import utr_spacer_rnafold_to_mrna

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
## 第5部分-mRNA疫苗设计
🔬 **当前进度**：基于默认的裂解子对上述肽段序列已完成CDS区域的密码子优化设计
⏳ **预计耗时**：计算时长跟有效肽段数量和长度呈正相关，请您耐心等待\n
"""
    writer(STEP5_DESC1)
    mrna_design_process_result.append(STEP5_DESC1)
    
    # 运行CDS组合工具
    cds_result = await concatenate_peptides_with_linker(mrna_input_file_path)
    if not cds_result:
        raise Exception("mRNA设计阶段CDS组合工具执行失败")
    INSERT_SPLIT = \
    f"""
    """   
    writer(INSERT_SPLIT)  

    STEP5_DESC2 = """
✅ **已完成步骤**：基于预设裂解子完成肽段-CDS区的密码子优化  
🔬 **当前进度**：正在进行mRNA疫苗的UTR设计（采用默认间隔子序列）  
⏳ **预计耗时**：2-5分钟（系统正在自动优化5'-UTR/3'-UTR调控元件）
"""
    writer(STEP5_DESC2)
    mrna_design_process_result.append(STEP5_DESC2)    
    # 运行UTR和RNAfold工具
    try:
        result = await utr_spacer_rnafold_to_mrna(cds_result)
    except Exception as e:
        import traceback
        traceback.print_exc()  # 打印完整堆栈
        raise
    
    
    if not result or not isinstance(result, tuple):
        raise Exception(f"mRNA设计阶段UTR和RNAfold工具执行失败：{result}")
    
    utr_spacer_rnafold_result_url, utr_spacer_rnafold_result_content = result
    # 输出结果
    INSERT_SPLIT = \
    f"""
    """   
    writer(INSERT_SPLIT)   

    STEP5_DESC3 = """
### mRNA筛选流程结果已获取，下载链接如下，在excel表中肽段信息一列中：linear代表线性mRNA，circular代码环状mRNA：\n
"""
    writer(STEP5_DESC3)
    mrna_design_process_result.append(STEP5_DESC3)
    
    # result_dict = {
    #     "type": "link",
    #     "url": utr_spacer_rnafold_result_url,
    #     "content": ""
    # }
    
    # writer(result_dict)
    # 提取链接信息
    rnafold_result_url = utr_spacer_rnafold_result_url['rnaflod_result_file_url']
    secondary_structure_urls = [
        v for i, (k, v) in enumerate(utr_spacer_rnafold_result_url.items()) 
        if i > 0  # 跳过第一个
    ]
    
    # 构建文件列表
    files = [{"name": "RNAFold_results.xlsx", "url": rnafold_result_url}]

    if len(secondary_structure_urls) >= 1:
        files.append({"name": "二级线性mRNA结构图.svg", "url": secondary_structure_urls[0]})
    if len(secondary_structure_urls) >= 2:
        files.append({"name": "二级环性mRNA结构图.svg", "url": secondary_structure_urls[1]})
    for i, url in enumerate(secondary_structure_urls[2:], 3):
        files.append({"name": f"二级结构图_{i}.svg", "url": url})

    # 生成Markdown链接
    markdown_link = "\n"+"\n".join(
        f"- [{file['name']}]({file['url']})" 
        for file in files
    ) + "\n"

    INSERT_SPLIT = \
    f"""
    """   
    writer(INSERT_SPLIT)
    writer("#NEO_RESPONSE#")
    writer(markdown_link)
    writer("#NEO_RESPONSE#\n")

    
    # 步骤完成描述
    STEP5_DESC4 = """
---

**说明**:  
• 上表显示肽段的最小自由能(MFE)二级结构预测结果  
• 括号表示法解析:  
- `(` / `)`: 配对的碱基对  
- `.`: 未配对碱基  
• 最后一列为自由能值（单位：kcal/mol）
"""
    mrna_design_process_result.append(STEP5_DESC4)
    
    return markdown_link