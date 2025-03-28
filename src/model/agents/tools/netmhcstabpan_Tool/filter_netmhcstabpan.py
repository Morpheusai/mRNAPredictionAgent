import re

def filter_netmhcstabpan_output(output_lines: list) -> str:
    """
    过滤 netMHCstabpan 的输出，提取关键信息并生成 Markdown 表格。
    
    参数:
        output_lines (list): netMHCstabpan 的输出文本列表，每行为一个字符串。
    
    返回:
        str: 包含标题、Markdown 表格及总结信息的字符串。
    """
    filtered_data = []
    additional_data = []
    
    # 提取标题（若输出行数足够，从倒数第三行获取标题，否则为空）
    header_line = f"**{output_lines[-3].strip()}**\n" if len(output_lines) >= 3 else ""
    
    for line in output_lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        
        parts = line.split()
        
        try:
            mhc = parts[1]              # MHC 等位基因
            peptide = parts[2]          # 肽序列
            pred = float(parts[4])      # 预测值
            thalf = float(parts[5])     # 半衰期
            rank_stab = float(parts[6]) # %Rank_Stab
            bind_level_match = re.search(r"(WB|SB)", line)
            bind_level = bind_level_match.group(0) if bind_level_match else "-"
            
            data_entry = {
                "Peptide": peptide,
                "MHC": mhc,
                "Pred": pred,
                "T_half": thalf,
                "Rank_Stab": rank_stab,
                "Bind_Level": bind_level
            }
            
            if bind_level in {"WB", "SB"}:
                filtered_data.append(data_entry)
            else:
                additional_data.append(data_entry)
        except (IndexError, ValueError):
            continue
    
    # 若无 WB/SB 但有其他数据，返回部分额外数据
    if not filtered_data and additional_data:
        filtered_data = additional_data[: min(5, len(additional_data))]
        warning_message = "\n**提示**: 未找到 WB 或 SB 结果"
    else:
        warning_message = ""
    
    # 按预测值降序排列
    sorted_data = sorted(filtered_data, key=lambda x: x['Pred'], reverse=True)
    
    #表明 表格output_lines 有内容，但没有任何符合 WB 或 SB 过滤条件的行
    if not sorted_data:
        return "\n**警告**: 未找到任何符合条件的肽段，请检查输入数据或参数设置。" + warning_message

    # 构建 Markdown 表格
    markdown_lines = [
        header_line,
        "| Peptide Sequence | MHC(HLA Allele) | Pred Score | T_half (h) | %Rank_Stab | Bind Level |",
        "|------------------|-----------------|------------|------------|------------|------------|"
    ]
    
    for item in sorted_data:
        markdown_lines.append(
            f"| {item['Peptide']} | {item['MHC']} | {item['Pred']:.3f} | {item['T_half']:.2f} | {item['Rank_Stab']:.2f} | {item['Bind_Level']} |"
        )
    markdown_lines.append(warning_message)
    markdown_lines.append(
            f"\n**当前结果**: 已完成肽段的筛选，我可以对 {sorted_data[0]['Peptide']}（最优肽段）进行结构预测，请问是否继续？"
        )
    
    return "\n".join(markdown_lines)
