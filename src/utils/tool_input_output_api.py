import json
import requests
from config import CONFIG_YAML
from src.utils.log import logger

handle_url = CONFIG_YAML["TOOL"]["COMMON"]["handle_tool_input_output_url"]

def send_tool_input_output_api(patient_id, prediction_id, mode, tool_name, parameters,flag):
    """
    统一调用 handle_tool_input_output 接口
    :param patient_id: 患者ID
    :param prediction_id: 预测ID
    :param mode: 0为前置，1为后置
    :param tool_name: 工具名
    :param parameters: 参数（dict）
    :flag:流程是否结束
    :return: None
    """
    payload = {
        "patient_id": patient_id,
        "prediction_id": prediction_id,
        "mode": mode,
        "tool_name": tool_name,
        "parameters": parameters,
        "flag":flag
    }
    headers = {
        'Content-Type': 'application/json'
    }
    logger.info(f"请求 handle_tool_input_output: url={handle_url}, payload={payload}")
    try:
        response = requests.post(
            handle_url,
            headers=headers,
            data=json.dumps(payload)
        )
        logger.info(f"handle_tool_input_output 返回状态码: {response.status_code}, 返回内容: {response.text}")
    except Exception as e:
        logger.error(f"调用 handle_tool_input_output 接口失败: {e}")