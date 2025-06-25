import os
import pandas as pd
from src.utils.log import logger

def save_excel(output: str, output_dir: str, output_filename: str) -> None:
    """
    将特定格式的序列数据保存为Excel文件
    
    参数:
        output: 包含序列数据的字符串，格式如示例
        output_dir: 保存目录的路径
        output_filename: 保存的文件名（不需要.xlsx后缀）
    
    返回:
        None
    """
    # 构建完整文件路径
    file_path = os.path.join(output_dir, output_filename)
    
    
    try:
        
        # 更严谨的分割方法：只在行首的>处分割
        lines = output.split('\n')
        records = []
        current_record = []
        
        for line in lines:
            if line.startswith('>'):
                if current_record:  # 如果已经有记录在收集，先保存
                    records.append('\n'.join(current_record))
                    current_record = []
                current_record.append(line)
            else:
                if current_record:  # 只有已经开始收集记录时才添加行
                    current_record.append(line)
        
        # 添加最后一个记录
        if current_record:
            records.append('\n'.join(current_record))
        
        logger.info(f"共解析到 {len(records)} 条序列记录")
        
        data = []
        for i, record in enumerate(records, 1):
            try:
                # 分割每行
                lines = record.strip().split('\n')
                
                # 解析第一行（肽段信息）
                header = lines[0][1:]  # 去掉开头的>
                
                # 解析肽段序列（第二行）
                peptide = lines[1] if len(lines) > 1 else ""
                
                # 解析MFE结构（第三行）
                mfe_structure = lines[2] if len(lines) > 2 else ""
                
                # 添加到数据列表
                data.append({
                    "肽段信息": f">{header}",
                    "肽段": peptide,
                    "MFE结构": mfe_structure
                })
                
                logger.debug(f"成功解析第 {i} 条记录: {header[:30]}...")  # 只显示header前30字符
                
            except Exception as e:
                logger.warning(f"解析第 {i} 条记录时出错，跳过该记录。错误: {str(e)}")
                logger.debug(f"问题记录内容: {record[:100]}...")  # 只显示前100字符
        
        # 创建DataFrame
        df = pd.DataFrame(data)
        
        # 保存到Excel
        df.to_excel(file_path, index=False)
    
    except pd.errors.EmptyDataError:
        error_msg = "无有效数据可保存，DataFrame为空"
        logger.error(error_msg)
        raise ValueError(error_msg)
        
        
    except Exception as e:
        error_msg = f"保存Excel文件时发生未知错误: {str(e)}"
        logger.error(error_msg)
        logger.debug(f"错误发生时的数据预览: {str(data[:1]) if data else '无数据'}")
        raise RuntimeError(error_msg)

# # 示例使用
# if __name__ == "__main__":
#     example_output = """
# >gi|33331470|gb|AAQ10915.1|     55  >>>  ISERI>LSTY       A1
# MAGRSGDNDEELLKAVRIIKILYKSNPYPEPKGSRQARKNRRRRWRARQRQIDSISERILSUYLGRSUEPVPLQLPPLERLHLDCREDCGUSGUQQSQGVEUGVGRPQISVESPVILGSRUKN
# ........................................................................................................................... (  0.00)
# >sequ>>nce
# GGGGAAAACCCC
# ((((....)))) ( -5.40)
# """
    
#     save_excel(example_output, "output_data", "peptide_data")