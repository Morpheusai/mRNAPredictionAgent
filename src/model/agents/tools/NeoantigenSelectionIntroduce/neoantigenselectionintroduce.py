import json

from langchain_core.tools import tool

@tool
def NeoantigenSelectionIntroduce() -> str:
    """
    NeoantigenSelectionIntroduce是介绍抗原筛选场景下的流程介绍的工具。
    Args:
        不需要传入任何参数
    Return:
        返回一段字符串
   """
    
    # 将预测流程写入变量
    process_steps = """
## 🔍 个体化 neoantigen 筛选流程简介
Neo 平台通过自动化的流程，帮助您从突变肽段中筛选出**具有潜力的个体化新抗原候选（neoantigen）**，用于后续多肽或mRNA疫苗开发。
我们集成了一套默认流程（NeoAntigenSelection），包含以下关键阶段：

---

## 1️⃣ 肽段生成与切割预测
工具：NetChop
将输入的突变蛋白序列切割为适合呈递的短肽（通常为8–11个氨基酸）。
✅ 默认保留 NetChop 预测结果中可信的切割位点。
## 2️⃣ TAP转运预测（抗原递呈能力评估）
工具：NetCTLpan
预测肽段进入内质网的转运效率，间接评估其是否具备递呈到细胞表面的潜力。
✅ 默认排除预测为 低转运效率 的肽段，提升后续预测质量。
## 3️⃣ pMHC结合亲和力预测
工具：NetMHCpan（默认使用）, TransPHLA, BigMHC_EL, ImmuneApp_PP
评估每条肽段与特定 HLA 分型之间的结合能力。
✅ 我们保留具有较高亲和力（%Rank < 2%）的候选肽段，进入下一步分析。
## 4️⃣免疫原性评分预测
工具：PRIME, BigMHC_IM（默认使用）, ImmuneApp_IM
对已筛选出的高亲和力肽段进行免疫激活潜力评估。
✅ 系统整合多个模型评分，并标记高免疫原性候选。
## 5️⃣ TCR识别能力预测（如有TCR数据）
工具：pMTnet, PISTE, NetTCR
如您提供了 TCR 的 CDR3 序列，系统将评估候选肽段是否可能被特定 T细胞识别。
✅ 进一步提高筛选肽段在实际免疫反应中的可信度。

---

## 💡 结果输出包含：
• 筛选通过的候选肽段
• 每条肽段的绑定亲和力与免疫原性评分
• （如提供TCR）识别评分结果
• 推荐标签与筛选理由说明

---

📉 若在任一阶段无合格肽段，流程将中止，并反馈原因（如切割失败、无高亲和力等），您可根据提示进行调整。

### 🔍 现在您已经了解了筛选流程的主要步骤和使用的工具。接下来，您可以选择：
**• 1️⃣🧪 [运行一个示例分析 →]**
    体验平台的完整筛选流程，看看实际的结果和输出形式。
**• 2️⃣📁 [上传我的数据开始分析 →]**
    准备好突变肽段数据？我们将引导您一步步完成分析。
    """
    
    # 返回保存流程步骤的变量
    result = {
        "type": "text",
        "content": process_steps
    }

    return json.dumps(result, ensure_ascii=False)
