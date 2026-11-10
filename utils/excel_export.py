"""Excel 导出统一工具。

项目里所有「导出为 Excel」的入口都走这里，避免每个蓝图各写一份 openpyxl 样式代码。
统一的内容：

- 表头：蓝底（4472C4）白色加粗、水平垂直居中
- 数据区：细边框（D0D7DE）、垂直居中、可选自动换行
- 列宽、冻结首行、自动筛选
- 单元格清洗：空值占位、控制字符、超长截断、公式注入防护
- 文件名：``<业务前缀>_YYYYmmdd_HHMMSS.xlsx``
- 响应：``send_file(as_attachment=True)``

调用方只负责查数据和把每行整理成列表，不再自己摆弄 openpyxl 样式。
"""

from datetime import datetime
from io import BytesIO

from flask import send_file
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# xlsx 的 MIME 类型，所有导出共用
XLSX_MIMETYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

HEADER_FILL_COLOR = "4472C4"
BORDER_COLOR = "D0D7DE"

# 空值在 Excel 里的占位符，避免出现空白单元格让人以为漏数据
EMPTY_PLACEHOLDER = "-"

# Excel 单元格最多 32767 字符，留一点余量
MAX_CELL_LENGTH = 32000

# 列宽上限，防止备注类超长文本把表格拉得没法看
MAX_COLUMN_WIDTH = 50
MIN_COLUMN_WIDTH = 8


def clean_cell_value(value, placeholder=EMPTY_PLACEHOLDER):
    """把数据库值转成可以安全写进 xlsx 的内容。

    - ``None`` / 空字符串 → ``placeholder``
    - ``int`` / ``float`` / ``datetime`` / ``date`` 原样返回，保留数值与日期类型，
      这样导出的金额、库存量在 Excel 里还能直接求和
    - 其它转字符串：清掉控制字符（openpyxl 遇到会抛 IllegalCharacterError）、
      截断到单元格上限；以 ``= + - @`` 开头的文本在写入时会被强制标记为文本，
      防止用户输入（详情、备注）被 Excel 当成公式执行
    """
    if value is None:
        return placeholder
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, bool):
        return "是" if value else "否"
    if not isinstance(value, str):
        # date / datetime / Decimal 等保持原类型，Excel 才能识别成日期或数值
        return value

    text = "".join(ch if ch >= " " or ch in "\n\t" else " " for ch in value)
    if text == "":
        return placeholder
    if len(text) > MAX_CELL_LENGTH:
        text = text[:MAX_CELL_LENGTH] + "…（已截断）"
    return text


def _header_style(cell):
    """表头：蓝底白字加粗、居中、细边框"""
    cell.font = Font(bold=True, color="FFFFFF")
    cell.fill = PatternFill(
        start_color=HEADER_FILL_COLOR, end_color=HEADER_FILL_COLOR, fill_type="solid"
    )
    cell.alignment = Alignment(horizontal="center", vertical="center")
    cell.border = _thin_border()


def _thin_border():
    side = Side(style="thin", color=BORDER_COLOR)
    return Border(left=side, right=side, top=side, bottom=side)


def _style_body(ws, wrap_text=True):
    """数据区：细边框 + 垂直居中；字符串强制按文本写，避免被当成公式"""
    if ws.max_row < 2:
        return
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for cell in row:
            cell.border = _thin_border()
            cell.alignment = Alignment(vertical="center", wrap_text=wrap_text)
            if isinstance(cell.value, str):
                cell.data_type = "s"


def auto_fit_columns(ws, max_width=MAX_COLUMN_WIDTH, min_width=MIN_COLUMN_WIDTH):
    """按内容长度算列宽，上限 max_width、下限 min_width"""
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        longest = 0
        for cell in col:
            if cell.value is None:
                continue
            longest = max(longest, len(str(cell.value)))
        ws.column_dimensions[col_letter].width = max(min_width, min(longest + 2, max_width))


def build_workbook(
    sheet_title,
    headers,
    rows,
    column_widths=None,
    wrap_text=True,
    freeze_header=True,
    auto_filter=True,
    placeholder=EMPTY_PLACEHOLDER,
):
    """生成一个排版统一的 Workbook。

    :param headers: 表头文本列表，顺序与 rows 的每行一致
    :param rows: 二维可迭代，每行元素个数与表头一致；已由调用方格式化好
    :param column_widths: 显式列宽列表；不传则按内容自动计算
    """
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title

    ws.append(list(headers))
    for cell in ws[1]:
        _header_style(cell)

    for row in rows:
        ws.append([clean_cell_value(value, placeholder) for value in row])

    _style_body(ws, wrap_text=wrap_text)

    if column_widths:
        for idx, width in enumerate(column_widths, start=1):
            ws.column_dimensions[get_column_letter(idx)].width = width
    else:
        auto_fit_columns(ws)

    if freeze_header:
        ws.freeze_panes = "A2"
    if auto_filter and headers:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{ws.max_row}"

    return wb


def excel_response(wb, filename_prefix):
    """把 Workbook 转成下载响应，文件名统一加时间戳"""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(
        output,
        mimetype=XLSX_MIMETYPE,
        as_attachment=True,
        download_name=f"{filename_prefix}_{stamp}.xlsx",
    )


def export_to_excel(filename_prefix, sheet_title, headers, rows, **kwargs):
    """一步导出：建表 → 排版 → 返回下载响应"""
    wb = build_workbook(sheet_title, headers, rows, **kwargs)
    return excel_response(wb, filename_prefix)
