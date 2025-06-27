import json
import requests
from config import CONFIG_YAML

handle_url = CONFIG_YAML["TOOL"]["COMMON"]["handle_tool_input_output_url"]

def send_tool_input_output_api(patient_id, prediction_id, mode, tool_name, parameters):
    """
    统一调用 handle_tool_input_output 接口
    :param patient_id: 患者ID
    :param prediction_id: 预测ID
    :param mode: 0为前置，1为后置
    :param tool_name: 工具名
    :param parameters: 参数（dict）
    :return: None
    """
    payload = {
        "patient_id": patient_id,
        "prediction_id": prediction_id,
        "mode": mode,
        "tool_name": tool_name,
        "parameters": parameters
    }
    headers = {
        'Content-Type': 'application/json'
    }
    try:
        requests.post(
            handle_url,
            headers=headers,
            data=json.dumps(payload)
        )
    except Exception as e:
        print(f"调用 handle_tool_input_output 接口失败: {e}") 