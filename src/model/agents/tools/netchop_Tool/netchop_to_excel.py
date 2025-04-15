import re
import pandas as pd
from pathlib import Path
from openpyxl.styles import Alignment
from openpyxl import load_workbook

from src.utils.log import logger

def save_excel(output: str, output_dir: str, output_filename: str) -> bool:
    """
    将数据保存到Excel文件（适用于netChop输出格式）
    
    Args:
        output: 要解析的原始文本数据
        output_dir: 输出目录路径 
        output_filename: 输出文件名
        
    Returns:
        bool: 成功返回True，失败返回False
    """
    try:
        # 数据解析 - 针对netChop输出格式
        table_pattern = re.compile(
            r"\s*(\d+)\s+([A-Z])\s+([^\s])\s+([\d.]+)\s+([^\s]+)"
        )
        matches = table_pattern.findall(output)
        
        if not matches:
            logger.error("未匹配到有效数据")
            return False

        # 创建DataFrame
        columns = [
            "Pos", "AA", "C", "score", "Ident"
        ]
        df = pd.DataFrame(matches, columns=columns)

        # 添加摘要信息
        summary_pattern = re.compile(r"Number of cleavage\s+[^\s]+.*")
        summary_match = summary_pattern.search(output)
        
        # 如果找到匹配的统计信息，将其添加到表格下方
        if summary_match:
            summary_row = [summary_match[0]] + [""] * (len(columns) - 1)  # 第一列是 summary_match[0]，其余列为空

            df.loc[len(df)] = summary_row

        # 准备输出路径
        output_path = Path(output_dir) / output_filename
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 写入Excel文件
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name="Results", index=False)
            
            # 获取workbook和worksheet对象
            workbook = writer.book
            worksheet = writer.sheets["Results"]
            
            # 设置合并单元格和居中
            if summary_match:
                worksheet.merge_cells(
                    start_row=len(df)+1,
                    start_column=1,
                    end_row=len(df)+1,
                    end_column=len(columns)
                )
                cell = worksheet.cell(row=len(df)+1, column=1)
                cell.alignment = Alignment(horizontal='center', vertical='center')
            
            # 调整列宽
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = (max_length + 2)
                worksheet.column_dimensions[column_letter].width = adjusted_width

            # 显式保存文件
            workbook.save(output_path)

        logger.info(f"Excel文件已成功保存至: {output_path}")
        return True

    except PermissionError as e:
        logger.error(f"文件权限错误: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"保存Excel时发生错误: {str(e)}", exc_info=True)
        return False