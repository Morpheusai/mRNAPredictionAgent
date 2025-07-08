from pydantic import BaseModel, Field

class NetchopParameters(BaseModel):
    input_filename: str = Field(
        description = "指定输入的fasta文件名",
        default="",
        examples = ["testA.fsa"],
    )
    cleavage_site_threshold: float = Field(
        description="设定切割位点的阈值(0~1 之间的浮点数), 值越高，预测越严格，返回的切割位点越少。",
        default=0.5,
        examples=[0.5],
    )
    model: int = Field(
        description="选择预测模型版本: 0-Cterm3.0(预测C端切割位点); 1-20S-3.0(预测蛋白酶体 20S 的切割位点)",
        default = 0,
        examples=[0],
    )
    format: int = Field(
        description = "控制输出格式: 0-长格式(默认，包含详细预测信息); 1-短格式(仅输出切割位点)",
        default = 0,
        examples=[0],
    )
    strict: int = Field(
        description="关闭严格模式: 严格模式（默认）会过滤低置信度预测，关闭后可能增加假阳性。",
        default = 0,
        examples=[0],
    )
    peptide_length: list = Field(
        description = "是否指定肽段长度, -1: 不指定，默认输出8-11长度的结果",
        default = [9],
        examples = [[9]],
    )

class NetctlpanParameters(BaseModel):
    input_filename: str = Field(
        description = "指定输入的fasta文件名",
        default="",  # 加上默认值
        examples=["testA.fsa"],
    )
    mhc_allele: str = Field(
        description="指定HLA等位基因（MHC 分子类型）",
        default = "HLA-A02:01",
        examples=["HLA-A02:01"],
    )
    peptide_length: int = Field(
        description = "是否指定肽段长度, -1: 不指定，默认输出8-11长度的结果",
        default = 9,
        examples = [8],
    )
    weight_of_tap: float = Field(
        description = "TAP 转运效率的权重(综合得分计算)，权重值越低，TAP 对综合得分的影响越小。调整此参数可优化预测模型。 ",
        default = 0.025,
        examples=[0],
    )
    weight_of_clevage: float = Field(
        description = "蛋白酶体切割效率的权重（综合得分计算）。比TAP权重大，表明切割效率对综合得分影响更显著。",
        default = 0.225,
        examples=[0],
    )
    epi_threshold: float = Field(
        description = "定义表位（epitope）的阈值，高于此值的肽段可能被标记为潜在表位。用于快速筛选高亲和力候选肽段，具体阈值需根据实验数据调整。  ",
        default = 1.0,
        examples=[0],
    )
    output_threshold: float = Field(
        description = "输出结果的得分阈值，仅显示高于此值的预测结果。默认值极低，通常会输出所有结果。若需筛选高亲和力肽段，可设为正值（如 1.0）。",
        default = -99.9,
        examples=[0],
    )
    sort_by: int = Field(
        description = \
f"""
控制输出结果的排序方式: 
  0: 按综合得分（Combined）排序
  1: 按MHC结合得分（MHC）排序
  2: 按蛋白酶体切割效率（Cleavage）排序
  3: 按TAP转运效率（TAP）排序  
  <0: 保持原始顺序（不排序）  
""",
        default = -1,
        examples=[0],
    )

class NetmhcpanParameters(BaseModel):
    input_filename: str = Field(
        description = "指定输入的fasta文件名",
        default="",  # 加上默认值
        examples=["testA.fsa"],
    )
    mhc_allele: str = Field(
        description="指定HLA等位基因（MHC 分子类型）",
        default = "HLA-A02:01",
        examples=["HLA-A02:01"],
    )
    peptide_length: int = Field(
        description = "是否指定肽段长度, -1: 不指定，默认输出8-11长度的结果",
        default = 9,
        examples = [8],
    )
    high_threshold_of_bp: float = Field(
        description = "设置高亲和力肽段的阈值。阈值越低，筛选出来的高亲和力肽段亲和力越好。",
        default = 0.5,
        examples=[0.1],
    )
    low_threshold_of_bp: float = Field(
        description = "设定低结合力肽段的阈值。阈值越高，筛选出来的低结合力肽段亲和力越差。 ",
        default = 2.0,
        examples=[2.1],
    )
    rank_cutoff: float = Field(
        description = \
f"""
控制输出结果的%Rank截断值。  
说明：
 - 若设置为正数（如5.0），则仅输出%Rank ≤ 5.0的肽段。
 - 若设置为负数（如默认值-99.9），则输出所有肽段（无论%Rank高低）。
 - 该参数用于灵活控制结果文件的体积和筛选范围。
""",
        default = -99.9,
        examples=[5.0],
    )

class BigmhcIMParameters(BaseModel):
    """Parameters for BigMHC-IM."""
    input_filename: str = Field(
        description = "指定输入的fasta文件名",
        default="",  # 加上默认值
        examples=["testA.fsa"],
    )
    mhc_allele: str = Field(
        description="指定HLA等位基因（MHC 分子类型）",
        default = "HLA-A02:01",
        examples=["HLA-A02:01"],
    )

class ToolOutput(BaseModel):
    """
    工具输出模型
    - output: 工具输出内容（字典）
    """
    tool_output: dict = Field(description="工具输出内容")

class ToolParameters:
    """Parameters for a tool."""
    def __init__(self, **kwargs):
        self.netchop_parameters = NetchopParameters(**(kwargs.get("netchop") or {}))
        self.netctlpan_parameters = NetctlpanParameters(**(kwargs.get("netctlpan") or {}))
        self.netmhcpan_parameters = NetmhcpanParameters(**(kwargs.get("netmhcpan") or {}))
        self.bigmhc_im_parameters = BigmhcIMParameters(**(kwargs.get("bigmhc_im") or {}))

    def get_netchop_parameters(self) -> NetchopParameters:
        return self.netchop_parameters
    
    def get_netctlpan_parameters(self) -> NetctlpanParameters:
        return self.netctlpan_parameters

    def get_netmhcpan_parameters(self) -> NetmhcpanParameters:
        return self.netmhcpan_parameters
    
    def get_bigmhc_im_parameters(self) -> BigmhcIMParameters:
        return self.bigmhc_im_parameters