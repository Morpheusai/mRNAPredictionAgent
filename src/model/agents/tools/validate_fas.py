import re
import sys
from pathlib import Path
import json
from langchain.tools import tool
from minio import Minio
from minio.error import S3Error
from io import StringIO

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

# 定义有效氨基酸集合和HLA分型正则表达式
valid_amino_acids = set('ACDEFGHIKLMNPQRSTVWYX')


@tool
def ValidateFastaFile(input_file):
    """
    Use the ValidateFastaFile tool to verify if the input format to the NetMHCpan model is correct
    Args:
        input_file: input the path address of the file
    Return:
        The result returned in the form of a dictionary as a string, with 'ok' being 0 indicating correct formatting and 'ok' being 1 indicating formatting issues
    """
    errors = []  # 错误列表
    current_header = None  # 当前正在处理的header
    current_sequence = []  # 当前正在处理的序列
    line_num = 0  # 当前行号
    last_was_header = False  # 上一行是否是header行

    #提取桶名和文件
    try:
        # 去掉 minio:// 前缀
        path_without_prefix = input_file[len("minio://"):]
        
        # 找到第一个斜杠的位置，用于分割 bucket_name 和 object_name
        first_slash_index = path_without_prefix.find("/")
        
        if first_slash_index == -1:
            return json.dumps({
            "type": "error",
            "ok": 1,
            "content": f"请上传需要验证的FASTA文件"
            }, ensure_ascii=False) 
        
        # 提取 bucket_name 和 object_name
        bucket_name = path_without_prefix[:first_slash_index]
        object_name = path_without_prefix[first_slash_index + 1:]
        
        # 打印提取结果（可选）
        # logger.info(f"Extracted bucket_name: {bucket_name}, object_name: {object_name}")
        
    except Exception as e:
        # logger.error(f"Failed to parse file_path: {file_path}, error: {str(e)}")
        return json.dumps({
            "type": "error",
            "ok": 1,
            "content": f"无法从 MinIO 读取文件: {str(e)}"
        }, ensure_ascii=False)    

    try:
        response = minio_client.get_object(bucket_name, object_name)
        file_content = response.read().decode("utf-8")
    except S3Error as e:
        return json.dumps({
            "type": "error",
            "ok": 1,
            "content": f"无法从 MinIO 读取文件: {str(e)}"
        }, ensure_ascii=False)    


    file_lines = StringIO(file_content).readlines()
    for line in file_lines:
        line_num += 1
        stripped = line.strip()

        # 处理空行
        if not stripped:
            if current_header is not None:
                errors.append(f"警告 行 {line_num}: 发现空行")
            continue

        # 处理header行
        if stripped.startswith('>'):
            # 前导内容检查
            if line.startswith(' ') or line.startswith('\t'):
                errors.append(f"错误 行 {line_num}: Header行包含前导空格")

            # 处理连续header行
            if last_was_header:
                errors.append(f"错误 行 {line_num}: 发现连续的header行")

            # 如果当前正在处理一个记录，检查是否有序列
            if current_header is not None and not current_sequence:
                errors.append(f"严重错误 记录 {current_header}: Header行后没有肽段序列")

            # 开始新的记录
            current_header = stripped
            current_sequence = []
            last_was_header = True
            continue

        # 处理序列行
        last_was_header = False

        # 检查序列中是否包含 '>'
        if '>' in stripped:
            errors.append(f"严重错误 行 {line_num}: 序列中包含 '>' 符号")

        # 检查序列中的无效字符
        for char in stripped:
            if char not in valid_amino_acids:
                errors.append(f"严重错误 行 {line_num}: 发现无效氨基酸符号 '{char}'")

        current_sequence.append(stripped)

    # 检查最后一个记录是否有序列
    if current_header is not None and not current_sequence:
        errors.append(f"严重错误 记录 {current_header}: Header行后没有肽段序列")

    # 返回结构化结果
    if not errors:
        result =  {
            "type": "validity",
            "ok": 0,
            "content": "文件格式完全符合标准，无需矫正！"
        }
    else:
        result =  {
            "type": "validity",
            "ok": 1,
            "content": errors
        }
    return json.dumps(result, ensure_ascii=False)



if __name__ == "__main__":
    input_file = r"src\model\agents\tools\test.fsa"
    result = ValidateFastaFile(input_file)
    print(result)
    # if result["ok"] == 1:
    #     print("检验发现以下问题：")
    #     for error in result["msg"]:
    #         print(error)
    #     print("\n文件格式不正确，请调用矫正函数进行校正。")
    # else:
    #     print(result["msg"])