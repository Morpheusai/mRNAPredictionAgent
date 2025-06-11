import os                                                                                                                                                                                    
import subprocess
import uuid

from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from io import BytesIO

from config import CONFIG_YAML 
from src.utils.log import logger
from src.utils.minio_utils import upload_file_to_minio

MD2PDF_WATERMARK_CONTENT = CONFIG_YAML["MD2PDF"]["watermark_content"]
MD2PDF_CSS_PATH = CONFIG_YAML["MD2PDF"]["css_path"]
MD2PDF_LOGO_PATH = CONFIG_YAML["MD2PDF"]["logo_path"]
MD2PDF_HEADER_CONTENT = CONFIG_YAML["MD2PDF"]["header_content"]

MINIO_BUCKET = CONFIG_YAML["MINIO"]["molly_bucket"]

def neo_md2pdf(
    md_content,
    watermark_text = MD2PDF_WATERMARK_CONTENT, 
    header_text = MD2PDF_HEADER_CONTENT,
    image_file_path = MD2PDF_LOGO_PATH,
    image_width = 40, 
):
    """ 
    为PDF文件添加水印
    
    参数:
        input_pdf_path (str): 输入的PDF文件路径
        output_pdf_path (str): 输出的PDF文件路径
        watermark_text (str): 水印文字
        header_text, 页脚
    """
    tmp_postfix = uuid.uuid4().hex
    temp_md_file = f"/mnt/data/temp/temp_watermark_{tmp_postfix}.md"
    temp_pdf_file = f"/mnt/data/temp/case_report_{tmp_postfix}.pdf"

    with open(temp_md_file, 'w', encoding='utf-8') as f:
        f.write(md_content)

    # 定义命令和参数
    command = ["md2pdf", "--css", MD2PDF_CSS_PATH, temp_md_file, temp_pdf_file]
    try:
        # 执行命令
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        logger.info("PDF生成成功！")
    except subprocess.CalledProcessError as e:
        logger.error(f"PDF生成失败，错误代码: {e.returncode}")
        logger.error("错误输出:", e.stderr)

    # 在Ubuntu上注册常用的中文字体
    font_paths = [ 
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',  # 文泉驿微米黑
        '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',    # 文泉驿正黑
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'  # Noto字体
    ]   
    registered = False
    for font_path in font_paths:
        if os.path.exists(font_path):
            try:                                                                                                                                                                             
                pdfmetrics.registerFont(TTFont('ChineseFont', font_path))
                registered = True
                break
            except Exception as error:
                logger.error(error)
 
    if not registered:
        raise Exception("未找到可用的中文字体，请确保已安装文泉驿或Noto字体")
 
    # 创建水印PDF
    packet = BytesIO()
    can = canvas.Canvas(packet, pagesize=letter)
 
    # 设置水印属性
    can.setFont("Helvetica", 30)
    can.setFillColorRGB(0.8, 0.8, 0.8, alpha=0.2)  # 浅灰色，透明度20%
 
    # 在每页上添加旋转的水印文字
    for i in range(1, 100):  # 足够多的重复
        can.saveState()
        can.translate(240, 100)  # 位置
        can.rotate(45)  # 旋转角度
        can.drawString(0, 0, watermark_text)
        can.restoreState()
        can.translate(0, 150)  # 垂直间距
 
    can.save()
 
    # 将水印PDF移动到开头
    packet.seek(0)
    watermark_pdf = PdfReader(packet)
    watermark_page = watermark_pdf.pages[0]
 
    # 读取原始PDF
    pdf_reader = PdfReader(temp_pdf_file)
    pdf_writer = PdfWriter()

    # 获取原始PDF的页面大小
    first_page = pdf_reader.pages[0]
    page_width = float(first_page.mediabox[2])
    page_height = float(first_page.mediabox[3])
 
    # 预先读取图片获取高度
    img = ImageReader(image_file_path)
    img_width, img_height = img.getSize()
    aspect_ratio = img_height / img_width
    image_height = image_width * aspect_ratio
 
    from datetime import datetime
 
    # 获取当前日期和时间
    current_time = datetime.now()
 
    # 格式化为 'YYYY-MM-DD HH:MM:SS' 形式
    formatted_time = current_time.strftime('%Y-%m-%d')

    for page_num, page in enumerate(pdf_reader.pages):
 
        # 创建一个内存中的PDF用于绘制页眉页脚
        packet = BytesIO()
 
        can = canvas.Canvas(packet, pagesize=(page_width, page_height))                                                                                                                      
 
        # 设置字体和大小
        can.setFont("ChineseFont", 12)
        header_content = f"{header_text} - 第 {page_num + 1} 页"
 
        # 计算文本宽度并居中
        text_width = can.stringWidth(header_content, "ChineseFont", 12)
        # 添加页眉
        can.drawString((page_width - text_width) / 2, page_height - 20, header_content)
 
        # 添加页脚
        img_x = (page_width - image_width - 50) / 2
        img_y = 10  # 底部留20单位的边距
        can.drawImage(image_file_path, img_x, img_y, width=image_width, height=image_height, preserveAspectRatio=True)
        can.drawString((page_width + 30) / 2, 15, formatted_time)
 
        # 添加分隔线
        can.line(30, page_height - 30, page_width - 30, page_height - 30)
        can.line(30, 35, page_width - 30, 35)
 
        can.save()
 
        # 将绘制的页眉页脚移动到开头
        packet.seek(0)
 
        new_pdf = PdfReader(packet)
 
        # 获取原始页面
        original_page = pdf_reader.pages[page_num]
 
        # 合并原始页面和页眉页脚
        original_page.merge_page(new_pdf.pages[0])
 
        # 合并水印
        original_page.merge_page(watermark_page)
 
        # 添加到输出PDF
        pdf_writer.add_page(original_page)

    # 写入输出文件
    with open(temp_pdf_file, "wb") as output_pdf:
        pdf_writer.write(output_pdf)
    
    final_filepath = upload_file_to_minio(
        temp_pdf_file,
        MINIO_BUCKET
    )

    return final_filepath