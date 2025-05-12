import pandas as pd

def filter_netmhcpan_excel(excel_path: str) -> str:
    """
    从 netMHCpan 的 Excel 输出中过滤数据，提取关键信息并生成 Markdown 表格
    
    Args:
        excel_path (str): netMHCpan 的 Excel 文件路径
        
    Returns:
        str: 生成的 Markdown 表格字符串
    """
    try:
        df = pd.read_excel(excel_path, header=None, names=[
            "Pos", "MHC", "Peptide", "Core", "Of", "Gp", "Gl", "Ip", "Il", 
            "Icore", "Identity", "Score_EL", "%Rank_EL", "Score_BA", 
            "%Rank_BA", "Aff(nM)", "BindLevel"
        ])
    except Exception as e:
        return f"**错误**: 无法读取Excel文件 - {str(e)}"

    # 识别所有蛋白质信息行的位置
    protein_indices = []
    for idx, row in df.iterrows():
        if isinstance(row["Pos"], str) and "Protein" in row["Pos"]:
            protein_indices.append(idx)
    
    # 如果没有找到蛋白质信息行，返回错误
    if not protein_indices:
        return "**错误**: Excel文件中未找到任何蛋白质信息行"
    
    # 分割数据到各个蛋白质块
    protein_blocks = []
    prev_idx = 0
    for protein_idx in protein_indices:
        protein_info = df.iloc[protein_idx]["Pos"]
        # 数据行为当前蛋白质信息行之前的所有行，直到上一个蛋白质信息行之后
        data_rows = df.iloc[prev_idx:protein_idx]
        protein_blocks.append({
            "protein_info": protein_info,
            "data": data_rows
        })
        prev_idx = protein_idx + 1  # 跳过当前蛋白质信息行
    
    # 处理最后一个蛋白质块之后的数据（如果有）
    if prev_idx < len(df):
        data_rows = df.iloc[prev_idx:]
        # 如果没有后续的蛋白质信息行，这些数据可能属于最后一个块？
        # 根据实际情况调整，这里假设不属于任何块
    
    results = []
    
    # 处理每个蛋白质块
    for block in protein_blocks:
        protein_info = block["protein_info"]
        data_df = block["data"]
        
        # 筛选 WB/SB 行
        filtered_data = []
        for _, row in data_df.iterrows():
            bind_level = None
            bind_value = row.get("BindLevel", "")
            if isinstance(bind_value, str):
                if "<= WB" in bind_value:
                    bind_level = "WB"
                elif "<= SB" in bind_value:
                    bind_level = "SB"
            
            if bind_level:
                try:
                    filtered_data.append({
                        "Peptide": row["Peptide"],
                        "MHC": row["MHC"],
                        "BindLevel": bind_level,
                        "Score_EL": float(row["Score_EL"]),
                        "%Rank_EL": float(row["%Rank_EL"]),
                        "Affinity": float(row["Aff(nM)"])
                    })
                except (ValueError, TypeError):
                    continue
        
        # 生成结果
        if not filtered_data:
            # results.append(f"**{protein_info}该肽段未发现高亲和力肽段** \n")
            pass
        else:
            # 按 Score_EL 降序排序
            sorted_data = sorted(filtered_data, key=lambda x: x['Score_EL'], reverse=True)
            
            # 生成Markdown表格
            table = [
                "| Peptide Sequence | MHC(HLA Allele) | Score_EL | %Rank_EL | Affinity (nM) | Bind Level |",
                "|------------------|-----------------|----------|----------|---------------|------------|"
            ]
            for item in sorted_data:
                table_row = (
                    f"| {item['Peptide']} | {item['MHC']} | "
                    f"{item['Score_EL']:.4f} | {item['%Rank_EL']} | "
                    f"{item['Affinity']} | {item['BindLevel']} |"
                )
                table.append(table_row)
            
            results.append(f"**{protein_info}**\n" + "\n".join(table) + "\n")
    
    if not results:
        return "**警告**: 未找到任何符合条件（WB/SB）的肽段"
    
    return "\n".join(results)