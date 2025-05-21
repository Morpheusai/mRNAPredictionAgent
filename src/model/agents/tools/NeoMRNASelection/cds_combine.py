import asyncio
import uuid
import sys
import os

from pathlib import Path
from dotenv import load_dotenv
from minio import Minio

load_dotenv()
current_file = Path(__file__).resolve()
project_root = current_file.parents[5]
sys.path.append(str(project_root))
from config import CONFIG_YAML
from src.utils.log import logger

# 配置信息
NEOMRNA_CONFIG = CONFIG_YAML["TOOL"]["NEOMRNA_SELECTION"]
CLEAVAGE_ENHANCER = NEOMRNA_CONFIG["cleavage_enhancer"] 
INPUT_TMP_DIR = NEOMRNA_CONFIG["input_tmp_dir"] 
OUTPUT_TMP_DIR = NEOMRNA_CONFIG["output_tmp_dir"] 
LINEARDESIGN_SCRIPT = CONFIG_YAML["TOOL"]["LINEARDESIGN"]["script"]
linear_design_dir = Path(LINEARDESIGN_SCRIPT).parents[0]

# MinIO 配置:
MINIO_CONFIG = CONFIG_YAML["MINIO"]
MINIO_ENDPOINT = MINIO_CONFIG["endpoint"]
MINIO_ACCESS_KEY = os.getenv("ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("SECRET_KEY")
MINIO_SECURE = MINIO_CONFIG.get("secure", False)

# 初始化 MinIO 客户端
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)

async def concatenate_peptides_with_linker(fasta_file):
    """
    将FASTA文件中的肽段用裂解子连接起来
    
    参数:
        fasta_file: FASTA文件路径
        
    返回:
        连接后的长肽段字符串
    """
    try:
        # 解析MinIO路径
        if not fasta_file.startswith("minio://"):
            raise ValueError("Invalid path format, must start with 'minio://'")
        
        path_without_prefix = fasta_file[len("minio://"):]
        first_slash = path_without_prefix.find("/")
        if first_slash == -1:
            raise ValueError("Invalid path format: missing bucket name or object path")
        
        bucket_name = path_without_prefix[:first_slash]
        object_name = path_without_prefix[first_slash+1:]
        
        logger.info(f"Processing file from MinIO - bucket: {bucket_name}, object: {object_name}")

        # 从MinIO一次性读取文件内容
        response = minio_client.get_object(bucket_name, object_name)
        file_content = response.read().decode('utf-8')
        response.close()
        response.release_conn()

        # 处理FASTA内容
        linker = CLEAVAGE_ENHANCER
        peptides = []
        current_peptide = []
        
        for line in file_content.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith('>'):
                if current_peptide:
                    peptides.append(''.join(current_peptide))
                    current_peptide = []
            else:
                current_peptide.append(line)
    
        # 添加最后一个肽段
        if current_peptide:
            peptides.append(''.join(current_peptide))
        
        # 用连接符连接所有肽段
        concatenated = linker.join(peptides)

        # 生成随机ID和文件路径
        random_id_input = uuid.uuid4().hex
        random_id_output = uuid.uuid4().hex
        #base_path = Path(__file__).resolve().parents[3]  # 根据文件位置调整层级
        input_dir = Path(INPUT_TMP_DIR)
        output_dir =Path(OUTPUT_TMP_DIR)

        # 创建目录
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        input_path = input_dir / f"{random_id_input}.fasta"
        out_path = output_dir / f"{random_id_output}.fasta"


        with open(input_path, 'w') as f_out:
            f_out.write(f">peptide1\n{concatenated}\n")    

        # 构建命令
        cmd = [
            "python",str(LINEARDESIGN_SCRIPT),
            "-f", str(input_path),  
            "-o", str(out_path),  

        ]
        # 启动异步进程
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=linear_design_dir 
        )

        # 处理输出
        stdout, stderr = await proc.communicate()

        if proc.returncode == 0:
            # 确认输出文件已生成
            if out_path.exists():
                return str(out_path)  # 返回输出文件路径
            else:
                logger.info("错误：LinearDesign执行成功但未生成输出文件")
                return None
        else:
            error_msg = stderr.decode().strip()
            logger.info(f"LinearDesign执行失败，错误信息: {error_msg}")
            return None    
    except Exception as e:
        logger.error(f"Error processing peptides: {str(e)}")
        raise    

async def main():
    try:
        result = await concatenate_peptides_with_linker("./test.fasta")
        print(result)
    except Exception as e:
        print(f"发生错误: {e}")

if __name__ == "__main__":
    asyncio.run(main())