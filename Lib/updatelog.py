import gspread
from gspread_formatting import *

class obslog():
    def __init__(self):
        self.gc = gspread.service_account()
        self.sh = self.gc.open("LOGtest")
        self.title = "MergedHeaderSheet3"
        self.ws = self.sh.add_worksheet(title=self.title, rows=200, cols=9)

        self.ws.freeze(rows=2)

# 각 열별로 1행~2행 세로 병합: A1:A2, B1:B2, ..., I1:I2
        for col in range(1, 10):               # 1..9
            self.ws.merge_cells(1, col, 2, col)     # (row_start=1, col_start=col, row_end=2, col_end=col)

        letters = ['UT', 'File', 'Tile ID', 'Object', 'EXP #', 'Exposure', 'Airmass', 'FWHM', 'Comments']
        self.ws.update([letters], range_name="A1:I1")          # gspread 6.x: values 먼저, range_name 키워드 인자

        fmt = CellFormat(
            textFormat=TextFormat(bold=True),       
            horizontalAlignment='CENTER',           
            verticalAlignment='MIDDLE'          
        )

        format_cell_range(self.ws, "A1:I2", fmt)


obslog = obslog()
#gc=gspread.service_account()
#sh=gc.open("LOGtest")

"""
title = "MergedHeaderSheet3"
ws = sh.add_worksheet(title=title, rows=200, cols=9)

# 상단 2행 고정
ws.freeze(rows=2)

# 각 열별로 1행~2행 세로 병합: A1:A2, B1:B2, ..., I1:I2
for col in range(1, 10):               # 1..9
    ws.merge_cells(1, col, 2, col)     # (row_start=1, col_start=col, row_end=2, col_end=col)

# 병합된 칸의 좌상단 셀(=각 열의 1행)에 a~i 채우기
letters = ['UT', 'File', 'Tile ID', 'Object', 'EXP #', 'Exposure', 'Airmass', 'FWHM', 'Comments']
#letters = [chr(ord('a') + i) for i in range(9)]   # ['a','b',...,'i']
ws.update([letters], range_name="A1:I1")          # gspread 6.x: values 먼저, range_name 키워드 인자

# 서식 정의
fmt = CellFormat(
    textFormat=TextFormat(bold=True),       # 굵게
    horizontalAlignment='CENTER',           # 가로 가운데
    verticalAlignment='MIDDLE'              # 세로 가운데
)

# A1:I2 범위(병합된 헤더) 서식 적용
format_cell_range(ws, "A1:I2", fmt)
"""
