PATIENT_REPORT_ONE= \
"""
## 🧾 Neo 平台个体化 Neoantigen 筛选报告
### 📌 一、病例摘要
{patient_case_report}

## 🔍 二、分析流程与使用工具
> 本次分析使用平台默认流程 NeoAntigenSelection，依次完成以下步骤：

| 步骤                     | 使用工具    | 默认参数 / 阈值               |
| :----------------------- | :---------- | :---------------------------- |
| 肽段切割预测             | NetChop     | cleavage_site_threshold = 0.5 |
| TAP 转运效率预测         | NetCTLpan   | TAP >= 0.0 视为高转运                      |
| pMHC 结合亲和力预测      | NetMHCpan   | %Rank ≤ 2 视为高亲和力        |
| 抗原呈递概率预测（EL）   | BigMHC_EL   | ≥ 0.0                         |
| 免疫原性预测             | BigMHC_IM   | ≥ 0.0                         |
| TCR 识别能力预测（如提供）| pMTnet      | PMTNET_rank ≥ 0.1             |

## 📊 三、逐步分析结果概览
> 下表展示每一阶段筛选结果的数量及进展情况：

| 阶段               | 描述                     | 结果数量（通过/总数） | 下载链接 |
| :----------------- | :----------------------- | :-------------------- | :------- |
| 肽段切割           | 生成短肽段               | {cleavage_count}               | {cleavage_link}   |
| TAP 转运预测       | 剔除低转运效率肽段       | {tap_count}                | {tap_link}  |
| pMHC 亲和力预测    | 保留高亲和力肽段（%Rank ≤ 2） | {affinity_count}                | {affinity_link}   |
| 抗原呈递概率评估（EL） | EL 得分 ≥ 0.0            | {binding_count}                  | {binding_link}   |
| 免疫原性预测（IM） | IM 得分 ≥ 0.0            | {immunogenicity_count}                  | {immunogenicity_link}   |
| TCR 识别预测（如有） | PMTnet Rank ≥ 0.1       | {tcr_count}                 | {tcr_link}   |

## ✅ 四、最终筛选结论
本次个体化筛选流程中，系统最终推荐以下肽段作为neoantigen候选（已通过全部筛选环节）：

{tcr_content}
> 可用于个体化疫苗设计，建议结合临床方案进一步评估。

## ⚠️ 五、免责声明
本报告为基于计算模型的辅助分析结果，预测结论不代表临床诊断、治疗建议或药物批准路径。所有结果需结合实验验证与专业医学判断使用，Neo 平台不对预测结果用于临床治疗带来的后果承担责任。
"""



PATIENT_REPORT_TWO= \
"""
## 🧾 Neo 平台个体化 Neoantigen 筛选报告
### 📌 一、病例摘要
{patient_case_report}

## 🔍 二、分析流程与使用工具
> 本次分析使用平台默认流程 NeoAntigenSelection，依次完成以下步骤：

| 步骤                     | 使用工具    | 默认参数 / 阈值               |
| :----------------------- | :---------- | :---------------------------- |
| 肽段切割预测             | NetChop     | cleavage_site_threshold = 0.5 |
| TAP 转运效率预测         | NetCTLpan   | TAP >= 0.0 视为高转运                      |
| pMHC 结合亲和力预测      | NetMHCpan   | %Rank ≤ 2 视为高亲和力        |
| 抗原呈递概率预测（EL）   | BigMHC_EL   | ≥ 0.0                         |
| 免疫原性预测             | BigMHC_IM   | ≥ 0.0                         |
| TCR 识别能力预测（如提供）| pMTnet      | PMTNET_rank ≥ 0.1             |

## 📊 三、逐步分析结果概览
> 下表展示每一阶段筛选结果的数量及进展情况：

| 阶段               | 描述                     | 结果数量（通过/总数） | 下载链接 |
| :----------------- | :----------------------- | :-------------------- | :------- |
| 肽段切割           | 生成短肽段               | {cleavage_count}               | {cleavage_link}   |
| TAP 转运预测       | 剔除低转运效率肽段       | {tap_count}                | {tap_link}  |
| pMHC 亲和力预测    | 保留高亲和力肽段（%Rank ≤ 2） | {affinity_count}                | {affinity_link}   |
| 抗原呈递概率评估（EL） | EL 得分 ≥ 0.0            | {binding_count}                  | {binding_link}   |
| 免疫原性预测（IM） | IM 得分 ≥ 0.0            | {immunogenicity_count}                  | {immunogenicity_link}   |
| TCR 识别预测（如有） | PMTnet Rank ≥ 0.1       | {tcr_count}                 | {tcr_link}   |

## ✅ 四、最终筛选结论

{tcr_content}


## ⚠️ 五、免责声明
本报告为基于计算模型的辅助分析结果，预测结论不代表临床诊断、治疗建议或药物批准路径。所有结果需结合实验验证与专业医学判断使用，Neo 平台不对预测结果用于临床治疗带来的后果承担责任。
"""