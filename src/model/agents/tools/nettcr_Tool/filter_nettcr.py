import pandas as pd

def filter_nettcr_output(output_path_xlsx: str) -> str:
    """
    解析 Excel 文件并生成动态 Markdown 表格（兼容任意列名和数量）
    
    Args:
        output_path_xlsx (str): Excel 文件路径
        
    Returns:
        str: 生成的 Markdown 表格字符串
    """
    try:
        # 读取 Excel 文件
        df = pd.read_excel(output_path_xlsx)
        
        # 检查数据是否为空
        if df.empty:
            return "**警告**: Excel 文件中没有数据"
            
        # 动态生成 Markdown 表头
        headers = df.columns.tolist()
        markdown_table = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |"
        ]
        
        # 动态生成数据行
        for _, row in df.iterrows():
            markdown_table.append(
                "| " + " | ".join(str(row[col]) for col in headers) + " |"
            )
        
        # 返回完整的 Markdown 表格
        return "\n".join(markdown_table)
        
    except FileNotFoundError:
        return f"**错误**: 文件未找到 - {output_path_xlsx}"
    except Exception as e:
        return f"**错误**: 处理 Excel 文件时出错 - {str(e)}"