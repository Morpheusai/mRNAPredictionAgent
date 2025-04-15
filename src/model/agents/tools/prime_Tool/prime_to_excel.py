import re
import pandas as pd
from pathlib import Path
from openpyxl.styles import Alignment
from openpyxl import load_workbook

from src.utils.log import logger

def save_excel(output_path_txt: str, output_dir: str, output_filename: str) -> bool:
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
        # 读取文本文件内容
        with open(output_path_txt, 'r') as f:
            content = f.read()
        
        # 找到第二个 "####################" 之后的内容
        sections = content.split('####################')
        if len(sections) < 3:
            logger.error("未找到有效的数据部分")
            return False
        
        data_section = sections[2].strip()  # 第二个分割后的部分是实际数据
        
        # 按行分割数据
        lines = data_section.split('\n')
        
        # 动态解析列：非空内容为一列，遇到空后下一个非空为新列
        data = []
        current_row = []
        for line in lines:
            line = line.strip()
            # 按空白字符分割，并过滤空字符串
            parts = [p for p in re.split(r'\s+', line) if p]
            current_row.extend(parts)
            data.append(current_row)
            current_row = []
        
        if not data:
            logger.error("未解析到有效数据")
            return False
        
        # 第一行是表头，其余是数据
        headers = data[0]
        rows = data[1:]
        
        # 创建DataFrame
        df = pd.DataFrame(rows, columns=headers)

        # 准备输出路径
        output_path = Path(output_dir) / output_filename
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 写入Excel文件
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name="Results", index=False)
            
            # 获取workbook和worksheet对象
            workbook = writer.book
            worksheet = writer.sheets["Results"]
            
            # 调整列宽
            for column in worksheet.columns:
                max_length = max(
                    len(str(cell.value)) if cell.value else 0
                    for cell in column
                )
                adjusted_width = max_length + 2
                worksheet.column_dimensions[column[0].column_letter].width = adjusted_width

            # 显式保存文件
            workbook.save(output_path)

        logger.info(f"Excel文件已成功保存至: {output_path}")
        return True

    except FileNotFoundError:
        logger.error(f"输入文件不存在: {output_path_txt}")
        return False
    except PermissionError:
        logger.error(f"无权限写入文件: {output_path}")
        return False
    except Exception as e:
        logger.error(f"保存Excel时发生错误: {str(e)}", exc_info=True)
        return False