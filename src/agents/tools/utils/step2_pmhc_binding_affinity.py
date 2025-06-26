import json
import uuid
import tempfile
import re
import pandas as pd

from io import BytesIO
from minio.error import S3Error
from typing import Tuple,List

from config import CONFIG_YAML
from src.utils.minio_utils import MINIO_CLIENT
from src.agents.tools.NetMHCPan.netmhcpan import NetMHCpan
from src.utils.minio_utils import download_from_minio_uri

NEOANTIGEN_CONFIG = CONFIG_YAML["TOOL"]["NEOANTIGEN_SELECTION"]
BIND_LEVEL_ALTERNATIVE = NEOANTIGEN_CONFIG["bind_level_alternative"]  
BIGMHC_EL_THRESHOLD = NEOANTIGEN_CONFIG["bigmhc_el_threshold"]

def extract_hla_and_peptides_from_fasta(
    fasta_minio_path: str
) -> Tuple[str, List[str]]:
    """
    解析 >peptide|HLA 格式的 FASTA 文件，返回原始FASTA的minio地址和所有HLA分型列表
    
    参数:
    - fasta_minio_path: MinIO路径，例如 minio://bucket/file.fasta
    
    返回:
    - tuple: (原始FASTA的minio地址, 所有HLA分型的列表)
    """
    local_path = tempfile.NamedTemporaryFile(delete=True).name
    download_from_minio_uri(fasta_minio_path, local_path)

    hla_list = []
    HLA_REGEX = re.compile(r"^(HLA-)?[ABC]\*\d{2}:\d{2}$")

    with open(local_path, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith(">") and "|" in line:
                parts = line[1:].split("|", 1)
                if len(parts) == 2 and HLA_REGEX.fullmatch(parts[1].strip()):
                    hla = parts[1].strip()
                    if not hla.startswith("HLA-"):
                        hla = "HLA-" + hla
                    hla_list.append(hla)

    if not hla_list:
        raise ValueError("未能从FASTA中解析出合法的HLA分型")

    return (fasta_minio_path, hla_list)


async def step2_pmhc_binding_affinity(
    cleavage_result_file_path: str, 
    mhc_allele: List[str],
    writer,
    mrna_design_process_result: list,
    neoantigen_message,
    tap_m
) -> tuple:
    """
    第二步：pMHC结合亲和力预测
    
    Args:
        cleavage_result_file_path: 切割结果文件路径
        netchop_final_result_str: 切割结果内容的字符串
        mhc_allele: MHC等位基因列表
        writer: 流式输出写入器
        mrna_design_process_result: 过程结果记录列表
    
    Returns:
        tuple: (bigmhc_el_result_file_path, fasta_str) 结果文件路径和FASTA内容
    """
    # mhc_allele_str = ",".join(mhc_allele)
    
    # 步骤开始描述
#     STEP2_DESC1 = f"""
# ## 第2部分-pMHC结合亲和力预测
# 基于NetMHCpan工具对下述内容进行pMHC亲和力预测 
# 当前输入文件内容: \n
# ```
# {netchop_final_result_str}
# ```
# \n参数设置说明：
# - MHC等位基因(mhc_allele): 指定用于预测的MHC分子类型
# - 高亲和力阈值(high_threshold_of_bp): (结合亲和力百分位数≤此值判定为强结合)
# - 低亲和力阈值(low_threshold_of_bp): (结合亲和力百分位数≤此值判定为弱结合)
# - 肽段长度(peptide_length): (预测时考虑的肽段长度范围)

# 当前使用配置：
# - 选用MHC allele: {mhc_allele_str}
# - 高亲和力阈值: 0.5%
# - 低亲和力阈值: 2%
# - 分析肽段长度: 8,9,10,11
# """
    STEP2_DESC1 = f"""
## 🎯 步骤 3：pMHC结合亲和力预测
目标：筛选与患者MHC分型{mhc_allele}具有良好结合能力的肽段
"""
    writer(STEP2_DESC1)
    mrna_design_process_result.append(STEP2_DESC1)
    
    # 运行NetMHCpan工具
    netmhcpan_result = await NetMHCpan.arun({
        "input_filename": cleavage_result_file_path,
        "mhc_allele": mhc_allele,
        "peptide_length ": -1 ,
        "high_threshold_of_bp ": 0.5,
        "low_threshold_of_bp ": 2.0,
        "rank_cutoff ": -99.9,
    })
    try:
        netmhcpan_result_dict = json.loads(netmhcpan_result)
    except json.JSONDecodeError:
        neoantigen_message[4]=f"0/{tap_m}"
        neoantigen_message[5]="pMHC结合亲和力预测阶段NetMHCpan工具执行失败"
        raise Exception("pMHC结合亲和力预测阶段NetMHCpan工具执行失败")
    
    if netmhcpan_result_dict.get("type") != "link":
        neoantigen_message[4]=f"0/{tap_m}"
        neoantigen_message[5]="pMHC结合亲和力预测阶段NetMHCpan工具执行失败"
        raise Exception(netmhcpan_result_dict.get("content", "pMHC结合亲和力预测阶段NetMHCpan工具执行失败"))
    
    netmhcpan_result_file_path = netmhcpan_result_dict["url"]
    
    # 读取NetMHCpan结果文件
    try:
        path_without_prefix = netmhcpan_result_file_path[len("minio://"):]
        bucket_name, object_name = path_without_prefix.split("/", 1)
        response = MINIO_CLIENT.get_object(bucket_name, object_name)
        excel_data = BytesIO(response.read())
        df = pd.read_excel(excel_data)
        df['BindLevel'] = df['BindLevel'].astype(str).replace('nan', '')
        
    except S3Error as e:
        neoantigen_message[4]=f"0/{tap_m}"
        neoantigen_message[5]=f"无法从MinIO读取NetMHCpan结果文件: {str(e)}"
        raise Exception(f"无法从MinIO读取NetMHCpan结果文件: {str(e)}")

    # 筛选高亲和力肽段
    sb_peptides = df[df['BindLevel'].str.strip().isin(BIND_LEVEL_ALTERNATIVE)]

    # 步骤中间描述
    INSERT_SPLIT = \
    f"""
    """   
    # writer(INSERT_SPLIT)        
    STEP2_DESC2 = f"""
### 第2部分-pMHC结合亲和力预测结束\n
pMHC结合亲和力预测结果已获取，结果如下：\n
{netmhcpan_result_dict['content']}\n
\n接下来筛选符合BindLevel为{BIND_LEVEL_ALTERNATIVE}要求的高亲和力的肽段，请稍后\n
"""
    # writer(STEP2_DESC2)
    mrna_design_process_result.append(STEP2_DESC2)
    
    if sb_peptides.empty:
        STEP2_DESC3 = f"""
未筛选到符合BindLevel为{BIND_LEVEL_ALTERNATIVE}要求的高亲和力的肽段，筛选流程结束
"""
        writer(STEP2_DESC3)
        mrna_design_process_result.append(STEP2_DESC3)
        neoantigen_message[4]=f"0/{tap_m}"
        neoantigen_message[5]=netmhcpan_result_file_path
        raise Exception("pMHC结合亲和力预测阶段结束，NetMHCpan工具未找到高亲和力肽段")
    

    # 构建FASTA内容
    fasta_content = []
    mhcpan_count = 0
    for idx, row in sb_peptides.iterrows():
        mhc_allele = row['MHC']
        peptide = row['Peptide']
        fasta_content.append(f">{peptide}|{mhc_allele}")
        fasta_content.append(peptide)
        mhcpan_count += 1
    netmhcpan_fasta_str = "\n".join(fasta_content)
    neoantigen_message[4]=f"{mhcpan_count}/{tap_m}"
    neoantigen_message[5]=netmhcpan_result_file_path
    # 上传FASTA文件到MinIO
    uuid_name = str(uuid.uuid4())
    netmhcpan_result_fasta_filename = f"{uuid_name}_netmhcpan.fasta"
    
    try:
        fasta_bytes = netmhcpan_fasta_str.encode('utf-8')
        fasta_stream = BytesIO(fasta_bytes)
        MINIO_CLIENT.put_object(
            "molly",
            netmhcpan_result_fasta_filename,
            data=fasta_stream,
            length=len(fasta_bytes),
            content_type='text/plain'
        )
    except Exception as e:
        neoantigen_message[6]=f"0/{mhcpan_count}"
        neoantigen_message[7]=f"上传FASTA文件失败: {str(e)}"
        raise Exception(f"上传FASTA文件失败: {str(e)}")
    
    STEP2_DESC7 = f"""
✅ 已识别出**{mhcpan_count}个亲和力较强的候选肽段**，符合进一步免疫原性筛选条件
"""
    writer(STEP2_DESC7)
    
    return f"minio://molly/{netmhcpan_result_fasta_filename}", mhcpan_count