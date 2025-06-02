import asyncio
import sys
import uuid
import os
import json

from pathlib import Path
from dotenv import load_dotenv
from minio import Minio
from minio.error import S3Error


load_dotenv()
current_file = Path(__file__).resolve()
project_root = current_file.parents[5]
sys.path.append(str(project_root))
from config import CONFIG_YAML

# MinIO 配置:
MINIO_CONFIG = CONFIG_YAML["MINIO"]
MINIO_ENDPOINT = MINIO_CONFIG["endpoint"]
MINIO_ACCESS_KEY = os.getenv("ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("SECRET_KEY")
MINIO_BUCKET = MINIO_CONFIG["molly_bucket"]
MINIO_SECURE = MINIO_CONFIG.get("secure", False)


NEOMRNA_CONFIG = CONFIG_YAML["TOOL"]["NEOMRNA_SELECTION"]
UTR5 = NEOMRNA_CONFIG["5_UTR"]  
UTR3 = NEOMRNA_CONFIG["3_UTR"]  
IRES = NEOMRNA_CONFIG["IRES"]
SPACER = NEOMRNA_CONFIG["spacer"] 
OUTPUT_TMP_DIR = NEOMRNA_CONFIG["output_tmp_dir"]

# 初始化 MinIO 客户端
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)

#检查minio是否可用
def check_minio_connection(bucket_name=MINIO_BUCKET):
    try:
        minio_client.list_buckets()
        if not minio_client.bucket_exists(bucket_name):
            minio_client.make_bucket(bucket_name)
        return True
    except S3Error as e:
        print(f"MinIO连接或bucket操作失败: {e}")
        return False

async def utr_spacer_rnafold_to_mrna(fasta_file, mRNA_type="both"):
    """
    处理FASTA文件中的每个密码子，添加UTR和spacer生成完整mRNA（线性和/或环状），并使用RNAFold工具筛选。
    
    参数:
        fasta_file: 输入的FASTA文件路径
        mRNA_type: 生成的mRNA类型，可选 "linear"、"circular" 或 "both"（默认）
        
    返回:
        tuple: (输出文件路径, 生成的mRNA数量)，str
    """
    from model.agents.tools.RNAFold.rnafold import RNAFold
    
    # 验证mRNA_type参数
    valid_types = ["linear", "circular", "both"]
    if mRNA_type.lower() not in valid_types:
        raise ValueError(f"Invalid mRNA_type. Must be one of: {valid_types}")

    minio_available = check_minio_connection()
    # 读取并解析输入FASTA文件
    sequences = []
    current_seq = []
    
    with open(fasta_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith('>'):
                if current_seq:
                    sequences.append(''.join(current_seq))
                    current_seq = []
            else:
                current_seq.append(line)
        if current_seq:
            sequences.append(''.join(current_seq))
    
    # 为每个密码子序列构建mRNA
    mrna_sequences = []
    for seq in sequences:
        if mRNA_type.lower() in ["linear", "both"]:
            # 线性mRNA：5'UTR + spacer + CDS + spacer + 3'UTR
            linear_mrna = f"{UTR5}{SPACER}{seq}{SPACER}{UTR3}"
            mrna_sequences.append(("linear", linear_mrna))
        
        if mRNA_type.lower() in ["circular", "both"]:
            # 环状mRNA：IRES + spacer + CDS + spacer + IRES
            circular_mrna = f"{IRES}{SPACER}{seq}{SPACER}{IRES}"
            mrna_sequences.append(("circular", circular_mrna))
    
    # 生成输出文件路径
    random_id = uuid.uuid4().hex
    output_dir = Path(OUTPUT_TMP_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"mrna_{random_id}.fasta"
    
    # 写入输出FASTA文件（标注序列类型）
    with open(output_path, 'w') as f_out:
        for i, (seq_type, mrna) in enumerate(mrna_sequences, 1):
            f_out.write(f">sequence_{i}_{seq_type}\n{mrna}\n")
    
    try:
        if minio_available:
            minio_client.fput_object(
                MINIO_BUCKET,
                f"mrna_{random_id}.fasta",
                str(output_path)
            )
            file_path = f"minio://molly/mrna_{random_id}.fasta"
            rnafold_result = await RNAFold.arun({"input_file": file_path})


            try:
                # 解析返回的JSON结果
                rnafold_result_dict = json.loads(rnafold_result)
            except json.JSONDecodeError:    
                raise

            if rnafold_result_dict.get("type") == "link":
                return rnafold_result_dict["url"],rnafold_result_dict["content"]
            else:
                return rnafold_result_dict["content"]
        else:
            raise 
    except S3Error as e:
        raise
    finally:
        # 如果 MinIO 成功上传，清理临时文件；否则保留
        if minio_available:
            output_path.unlink(missing_ok=True)
            # fasta_file.unlink(missing_ok=True)


# 使用示例

async def main():
    input_file = "./test.fasta"
    result = await utr_spacer_rnafold_to_mrna(input_file)
    print(result)

if __name__ == "__main__":
    asyncio.run(main())