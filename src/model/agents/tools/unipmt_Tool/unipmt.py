import asyncio
import json
import os
import pandas as pd
import numpy as np
import pickle
import re
import uuid
from pathlib import Path
from langchain_core.tools import tool
import subprocess
import sys
from urllib.parse import urlparse
from minio import Minio
from minio.error import S3Error

current_file = Path(__file__).resolve()
project_root = current_file.parents[5]
sys.path.append(str(project_root))
from src.utils.log import logger
from config import CONFIG_YAML
from src.model.agents.tools.unipmt_Tool.parse_unipmt_results import parse_unipmt_results

# UniPMT 工具配置
unipmt_script = CONFIG_YAML["TOOL"]["UNIPMT"]["script_path"]
python_bin = CONFIG_YAML["TOOL"]["UNIPMT"]["python_bin"]
input_tmp_dir = CONFIG_YAML["TOOL"]["UNIPMT"]["input_tmp_dir"]
# output_tmp_dir = CONFIG_YAML["TOOL"]["UNIPMT"]["tmp_output_dir"]
# # 创建临时目录
# os.makedirs(input_tmp_dir, exist_ok=True)
# os.makedirs(output_tmp_dir, exist_ok=True)
# MinIO 配置
MINIO_CONFIG = CONFIG_YAML["MINIO"]
MINIO_ENDPOINT = MINIO_CONFIG["endpoint"]
MINIO_ACCESS_KEY = os.getenv("ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("SECRET_KEY")
MINIO_SECURE = MINIO_CONFIG.get("secure", False)
MINIO_BUCKET = CONFIG_YAML["MINIO"]["unipmt_bucket"]

# 配置固定路径
nodes_peptides_csv = CONFIG_YAML["TOOL"]["UNIPMT"]["nodes_peptides_csv"]
nodes_mhc_csv = CONFIG_YAML["TOOL"]["UNIPMT"]["nodes_mhc_csv"]
nodes_tcr_csv = CONFIG_YAML["TOOL"]["UNIPMT"]["nodes_tcr_csv"]
p_features_path = CONFIG_YAML["TOOL"]["UNIPMT"]["p_features_path"]
t_features_path = CONFIG_YAML["TOOL"]["UNIPMT"]["t_features_path"]
m_features_path =   CONFIG_YAML["TOOL"]["UNIPMT"]["m_features_path"]
unipmt_input_file_path = CONFIG_YAML["TOOL"]["UNIPMT"]["unipmt_input_file_path"]

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)
if not minio_client.bucket_exists(MINIO_BUCKET):
    minio_client.make_bucket(MINIO_BUCKET)
def download_file_from_minio(minio_path: str, local_dir: str):
    """
    从 MinIO 下载文件到本地目录
    """
    if not minio_path.startswith('minio://'):
        raise ValueError("输入路径必须是 MinIO 格式，如 'minio://bucket/file'")

    url_parts = urlparse(minio_path)
    bucket_name = url_parts.netloc
    object_name = url_parts.path.lstrip('/')

    local_path = Path(local_dir) / Path(object_name).name
    Path(local_dir).mkdir(parents=True, exist_ok=True)

    if not local_path.exists():
        logger.info(f"Downloading {minio_path} to {local_path}")
        minio_client.fget_object(bucket_name, object_name, str(local_path))

    return str(local_path)


def generate_pmt_data(input_file: str):
    """
    根据输入的 CSV 文件，生成 PMT 的 pkl 文件，自动处理异常数据。

    参数:
    - input_file: str，输入文件路径（csv，必须包含 Peptide, MHC, TCR 三列）

    输出:
    - 保存 pmt_data.pkl, statics.pkl 和 dropped_samples_log.csv 到输出目录
    """
    if not input_file.startswith("minio://"):
        raise ValueError(f"无效的 MinIO 路径: {input_file}，请确保路径以 'minio://' 开头")
    input_file = download_file_from_minio(input_file, input_tmp_dir)

    # 加载官方映射
    peptides_df = pd.read_csv(nodes_peptides_csv)
    mhc_df = pd.read_csv(nodes_mhc_csv)
    tcr_df = pd.read_csv(nodes_tcr_csv)

    peptide_seq2id = {row['sequence']: int(row['id'][1:]) for _, row in peptides_df.iterrows()}
    mhc_seq2id = {row['category']: int(row['id'][1:]) for _, row in mhc_df.iterrows()}
    tcr_seq2id = {row['sequence']: int(row['id'][1:]) for _, row in tcr_df.iterrows()}

    # 加载特征
    p_features = np.load(p_features_path)
    t_features = np.load(t_features_path)
    m_features = np.load(m_features_path)

    p_max = p_features.shape[0] - 1
    m_max = m_features.shape[0] - 1
    t_max = t_features.shape[0] - 1
    logger.info(f"p_max: {p_max}, m_max: {m_max}, t_max: {t_max}")
    print(f"p_max: {p_max}, m_max: {m_max}, t_max: {t_max}")

    # 读取你的输入csv
    your_df = pd.read_csv(input_file)

    # 初始化
    pmt_data = []
    drop_records = []

    # 生成pmt_data
    for idx, row in your_df.iterrows():
        try:
            p_id = peptide_seq2id[row['Peptide']]
            m_id = mhc_seq2id[row['MHC']]
            t_id = tcr_seq2id[row['TCR']]

            if p_id > p_max or m_id > m_max or t_id > t_max:
                drop_records.append({'reason': 'ID超界', **row.to_dict()})
                continue

            label = 1  # 默认正样本
            pmt_data.append([p_id, m_id, t_id, label])

        except KeyError as e:
            drop_records.append({'reason': f'找不到映射 {e}', **row.to_dict()})
            continue

    pmt_data = np.array(pmt_data)

    logger.info(f"成功保留 {len(pmt_data)} 条样本，丢弃 {len(drop_records)} 条非法样本")
    # 保存输出
    os.makedirs(unipmt_input_file_path, exist_ok=True)
    with open(os.path.join(unipmt_input_file_path, 'pmt_data.pkl'), 'wb') as f:
        pickle.dump(pmt_data, f)

    statics = {
        'p_num': p_features.shape[0],
        'm_num': m_features.shape[0],
        't_num': t_features.shape[0],
    }
    with open(os.path.join(unipmt_input_file_path, 'statics.pkl'), 'wb') as f:
        pickle.dump(statics, f)

    # 保存丢弃日志
    if drop_records:
        drop_log = pd.DataFrame(drop_records)
        drop_log.to_csv(os.path.join(unipmt_input_file_path, 'dropped_samples_log.csv'), index=False)
        # print(f"丢弃日志已保存到 {unipmt_input_file_path}/dropped_samples_log.csv")

    logger.info(f"已保存 pmt_data.pkl, statics.pkl 及 dropped_samples_log！输出目录: {unipmt_input_file_path}")
    return "输入数据转换pkl文件成功！"

def convert_ids_to_sequences(input_file: str, peptide_node_file: str, mhc_node_file: str, tcr_node_file: str):
    """
    将预测结果的 ID 转换为序列，并保存转换后的文件。
    
    参数:
    - input_file: 预测结果的 CSV 文件路径（包含 ID）
    - peptide_node_file: 肽节点映射文件路径
    - mhc_node_file: MHC 节点映射文件路径
    - tcr_node_file: TCR 节点映射文件路径
    
    返回:
    - output_file: 转换后的文件路径
    """
    output_file = input_file
    
    # 检查文件存在
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"输入文件不存在: {input_file}")
    if not os.path.exists(peptide_node_file):
        raise FileNotFoundError(f"节点文件不存在: {peptide_node_file}")
    if not os.path.exists(mhc_node_file):
        raise FileNotFoundError(f"节点文件不存在: {mhc_node_file}")
    if not os.path.exists(tcr_node_file):
        raise FileNotFoundError(f"节点文件不存在: {tcr_node_file}")
    
    logger.info("开始读取...")

    
    # 读取预测结果
    df = pd.read_csv(input_file)
    
    # 读取节点映射
    peptides_df = pd.read_csv(peptide_node_file)
    mhc_df = pd.read_csv(mhc_node_file)
    tcr_df = pd.read_csv(tcr_node_file)
    
    # 建立 ID → sequence 的映射表
    pid2seq = {int(row['id'][1:]): row['sequence'] for _, row in peptides_df.iterrows()}
    mid2seq = {int(row['id'][1:]): row['category'] for _, row in mhc_df.iterrows()}
    tid2seq = {int(row['id'][1:]): row['sequence'] for _, row in tcr_df.iterrows()}
    
    logger.info(f"读取到 {len(pid2seq)} 个 Peptides, {len(mid2seq)} 个 MHCs, {len(tid2seq)} 个 TCRs")
    
    # 反查序列
    df['Peptide'] = df['Peptide'].map(pid2seq)
    df['MHC'] = df['MHC'].map(mid2seq)
    df['TCR'] = df['TCR'].map(tid2seq)
    
    # 调整列顺序
    df = df[['Peptide', 'MHC', 'TCR', 'prob', 'label']]
    
    # 保存
    df.to_csv(output_file, index=False)
    
    logger.info(f"成功保存转换后的文件到 {output_file}")
    
    return output_file


async def run_unipmt(input_file: str):
    """
    运行 UniPMT 工具，无需参数，直接执行，并返回JSON格式的结果。
    """
    try:
        # 生成 PMT 数据
        generate_pmt_data(input_file=input_file)
        logger.info(f"生成 PMT 数据成功！")

        # exit()
    except Exception as e:
        logger.error(f"生成 PMT 数据失败: {e}")
        return json.dumps({
            "type": "text",
            "content": f"生成 PMT 数据失败: {e}"
        }, ensure_ascii=False)
        
    if not Path(unipmt_script).exists():
        error_msg = f"UniPMT脚本不存在: {unipmt_script}"
        logger.error(error_msg)
        return json.dumps({
            "type": "text",
            "content": error_msg
        }, ensure_ascii=False)

    command = [python_bin, unipmt_script]
    logger.info(f"执行 UniPMT 命令: {' '.join(command)}")
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.path.dirname(unipmt_script)
        )

        stdout, stderr = await process.communicate()
        stdout_text = stdout.decode().strip()
        stderr_text = stderr.decode().strip()
        # print(f"stdout: {stdout_text}")
        # print(f"stderr: {stderr_text}")
        
        if process.returncode != 0:
            logger.error(f"UniPMT 执行失败，退出码: {process.returncode}")
            logger.error(f"stderr: {stderr_text}")
            raise subprocess.CalledProcessError(
                returncode=process.returncode,
                cmd=command,
                output=f"stdout: {stdout_text}\nstderr: {stderr_text}"
            )
        
        match = re.search(r"Saved predictions to (.*)", stdout_text)
        if match:
            pred_path = match.group(1).strip()
            try:
                # 转换 ID 为序列
                converted_file = convert_ids_to_sequences(
                    input_file=pred_path,
                    peptide_node_file=nodes_peptides_csv,
                    mhc_node_file=nodes_mhc_csv,
                    tcr_node_file=nodes_tcr_csv
                )
                object_name = os.path.basename(converted_file)
                minio_client.fput_object(MINIO_BUCKET, object_name, converted_file)
                minio_url = f"minio://{MINIO_BUCKET}/{object_name}"
                
                os.remove(converted_file)
                logger.info(f"Deleted local file: {converted_file}")

                content = parse_unipmt_results(minio_url)
                return json.dumps({
                    "type": "link",
                    "url": minio_url,
                    "content": f"UniPMT 执行成功\n\n{content}"
                }, ensure_ascii=False)
            except S3Error as e:
                return json.dumps({
                    "type": "text",
                    "content": f"UniPMT 执行成功，但上传到 MinIO 失败: {e}"
                }, ensure_ascii=False)
        else:
            return json.dumps({
                "type": "text",
                "content": "UniPMT 执行成功，但未找到输出文件路径"
            }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"UniPMT 工具执行失败: {e}")
        return json.dumps({
            "type": "text",
            "content": f"UniPMT 工具执行失败: {e}"
        }, ensure_ascii=False)
@tool
def UniPMT(input_file: str):
    """
    使用异步方式运行 UniPMT 工具，并返回 JSON 格式的结果。
    """
    try:
        # 运行 UniPMT 工具
        return asyncio.run(run_unipmt(input_file))
    except Exception as e:
        logger.error(f"UniPMT 工具执行失败: {e}")
        return json.dumps({
            "type": "text",
            "content": f"UniPMT 工具执行失败: {e}"
        }, ensure_ascii=False)

# 本地测试
if __name__ == "__main__":
    input_file = "minio://molly/22173dfb-6454-4e52-a174-590f0e8edeb7_predict_unipmt.csv"
    print(asyncio.run(run_unipmt(input_file)))
