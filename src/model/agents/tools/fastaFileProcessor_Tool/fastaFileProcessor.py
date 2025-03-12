import json
import sys

from io import StringIO
from io import BytesIO
from langchain.tools import tool
from minio import Minio
from minio.error import S3Error
from pathlib import Path




current_file = Path(__file__).resolve()
project_root = current_file.parents[4] 
# 将项目根目录添加到 sys.path
sys.path.append(str(project_root))
from config import CONFIG_YAML

# MinIO 配置:
MINIO_CONFIG = CONFIG_YAML["MINIO"]
MINIO_ENDPOINT = MINIO_CONFIG["endpoint"]
MINIO_ACCESS_KEY = MINIO_CONFIG["access_key"]
MINIO_SECRET_KEY = MINIO_CONFIG["secret_key"]
MINIO_SECURE = MINIO_CONFIG.get("secure", False)

# 初始化 MinIO 客户端
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)

# 定义有效氨基酸集合
valid_amino_acids = set('ACDEFGHIKLMNPQRSTVWYX')

def process_record(header, sequence_lines, records, errors, line_num):
    """处理单个FASTA记录"""
    sequence = ''.join(sequence_lines).upper()
    valid_chars = []
    for char in sequence:
        if char in valid_amino_acids:
            valid_chars.append(char)
        else:
            errors.append(f"严重错误 行 {line_num}: 发现无效氨基酸符号 '{char}'")    
    cleaned_sequence = ''.join(valid_chars)

    # 长度检查
    if not 8 <= len(cleaned_sequence) <= 20000:
        errors.append(f"严重错误 记录 {header}: 无效序列长度 ({len(cleaned_sequence)} aa)")
        return  # 跳过无效记录

    records.append((header, cleaned_sequence))

def format_output(records):
    """生成校正后的FASTA格式"""
    output = []
    for header, seq in records:
        output.append(header)
        # 按标准FASTA格式换行（每行70个字符）
        for i in range(0, len(seq), 70):
            output.append(seq[i:i+70])
    return '\n'.join(output)

@tool
def FastaFileProcessor(input_file):
    """
    Verify and correct the input format of the NetMHCpan model using the FastaFileProcessor tool
    Args：
    input_file： Enter the minio path address of the input file
    Return:
    Return whether there are errors or the corrected file address
    """
    try:
        errors = []  # 错误列表
        records = []  # 用于存储解析后的FASTA记录
        current_header = None  # 当前正在处理的header
        current_sequence = []  # 当前正在处理的序列
        line_num = 0  # 当前行号
        last_was_header = False  # 上一行是否是header行

        # 提取桶名和文件
        try:
            # 去掉 minio:// 前缀
            path_without_prefix = input_file[len("minio://"):]
            
            # 找到第一个斜杠的位置，用于分割 bucket_name 和 object_name
            first_slash_index = path_without_prefix.find("/")
            
            if first_slash_index == -1:
                return json.dumps({
                    "type": "text",
                    "content": f"请上传需要矫正的FASTA文件"
                }, ensure_ascii=False)
            
            # 提取 bucket_name 和 object_name
            bucket_name = path_without_prefix[:first_slash_index]
            object_name = path_without_prefix[first_slash_index + 1:]
            
        except Exception as e:
            return json.dumps({
                "type": "text",
                "content": f"无法解析文件路径: {str(e)}"
            }, ensure_ascii=False)    

        # 从 MinIO 读取文件内容
        try:
            response = minio_client.get_object(bucket_name, object_name)
            file_content = response.read().decode("utf-8")
        except S3Error as e:
            return json.dumps({
                "type": "text",
                "content": f"无法从 MinIO 读取文件: {str(e)}"
            }, ensure_ascii=False)    

        # 解析文件内容
        file_lines = StringIO(file_content).readlines()
        for line in file_lines:
            line_num += 1
            stripped = line.strip()

            # 处理空行
            if not stripped:
                if current_header is not None:
                    errors.append(f"警告 行 {line_num}: 发现空行,已自动删除")
                continue

            # 处理header行
            if stripped.startswith('>'):
                # 前导内容检查
                if line.startswith(' ') or line.startswith('\t'):
                    errors.append(f"错误 行 {line_num}: Header行包含前导空格，已自动删除")

                # 处理连续header行
                if last_was_header:
                    errors.append(f"错误 行 {line_num}: 发现连续的header行，已自动合并")

                # 如果当前正在处理一个记录，先保存
                if current_header is not None:
                    process_record(current_header, current_sequence, records, errors, line_num)

                # 如果当前正在处理一个记录，检查是否有序列
                if current_header is not None and not current_sequence:
                    errors.append(f"严重错误 记录 {current_header}: Header行后没有肽段序列")    

                # 开始新的记录
                current_header = stripped.lstrip()  # 去掉前导空格
                current_sequence = []
                last_was_header = True
                continue

            # 处理序列行
            last_was_header = False
            # 检查序列中是否包含 '>'
            if '>' in stripped:
                errors.append(f"严重错误 行 {line_num}: 序列中包含 '>' 符号,已经进行换行，可能需要您手动调整")
                # 拆分序列
                parts = stripped.split('>')
                # 第一部分属于当前序列
                current_sequence.append(parts[0])
                # 处理剩余部分
                for part in parts[1:]:
                    # 保存当前记录
                    if current_header is not None:
                        process_record(current_header, current_sequence, records, errors, line_num)
                        # 开始新的记录
                        current_header = '>' + part
                        current_sequence = []
                    else:
                        process_record(">", current_sequence, records, errors, line_num)
                        # 开始新的记录
                        current_header = '>' + part
                        current_sequence = []   
            else:
                # 如果没有 '>'，直接添加到当前序列
                current_sequence.append(stripped)

        # 处理最后一个记录
        if current_header is not None:
            process_record(current_header, current_sequence, records, errors, line_num)

        # 检查最后一个记录是否有序列
        if current_header is not None and not current_sequence:
            errors.append(f"严重错误 记录 {current_header}: Header行后没有肽段序列")

        # 生成校正后的FASTA内容
        corrected_fasta = format_output(records)

        # 返回结构化结果
        if not errors:
            result =  {
                "type": "text",
                "content": "文件格式已完成验证，符合标准格式，请问是否继续？"
            }
        else:   
            # 将校正后的文件上传回 MinIO
            try:
                corrected_bytes = corrected_fasta.encode("utf-8")
                data_stream = BytesIO(corrected_bytes)
                # 将校正后的内容上传到 MinIO
                minio_client.put_object(
                    bucket_name,
                    object_name,  # 覆盖原始文件
                    data_stream,
                    len(corrected_bytes)
                )
                result = {
                    "type": "link",
                    "url": input_file,  # 返回原始 MinIO 路径
                    "content": f"已经完成矫正，若有严重错误需要手动修改{errors}"
                }
            except S3Error as e:
                result = {
                    "type": "text",
                    "msg": f"无法将校正后的文件上传到 MinIO: {str(e)}"
                }
    except Exception as e:
        # 捕获其他未预见的异常
        result = {
            "type": "text",
            "content": f"未知错误：{str(e)}"
        }
    return json.dumps(result, ensure_ascii=False)

# if __name__ == "__main__":
#     input_file = r"src\model\agents\tools\test.fsa"
#     correction_result = FastaFileProcessor(input_file)

#     # 输出校正结果
#     print(correction_result)