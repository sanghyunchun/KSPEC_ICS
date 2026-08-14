import gspread
from gspread_formatting import *

class obslog():
    def __init__(self, dir_name):
        self.gc = gspread.service_account()
        self.sh = self.gc.open("CMDLOG")
        self.title = dir_name
        self.ws, self.created = self._get_or_create_worksheet()

        if self.created:
            self._setup_worksheet()

        self.message = f'{self.title} command log {"created" if self.created else "loaded"}'

    def _get_or_create_worksheet(self):
        try:
            return self.sh.worksheet(self.title), False
        except gspread.WorksheetNotFound:
            return self.sh.add_worksheet(
                title=self.title,
                rows=200,
                cols=9,
                index=0
            ), True

    def _setup_worksheet(self):
        self.ws.freeze(rows=2)

# 각 열별로 1행~2행 세로 병합: A1:A2, B1:B2, ..., I1:I2
        for col in range(1, 10):               # 1..9
            self.ws.merge_cells(1, col, 2, col)     # (row_start=1, col_start=col, row_end=2, col_end=col)

        letters = ['UT', 'PROJID', 'TILE ID', 'OBJTYPE', 'OBJECT', 'EXPOSURE', 'EXP #', 'Comments']
        self.ws.update([letters], range_name="A1:I1")          # gspread 6.x: values 먼저, range_name 키워드 인자

        fmt = CellFormat(
            textFormat=TextFormat(bold=True),       
            horizontalAlignment='CENTER',           
            verticalAlignment='MIDDLE'          
        )

        format_cell_range(self.ws, "A1:I2", fmt)


    def add_log(
        self,
        ut,
        projid,
        tile_id,
        objtype,
        object_name,
        exposure,
        exp_num,
        comments=""
    ):
        values = [
            ut,
            projid,
            tile_id,
            objtype,
            object_name,
            exposure,
            exp_num,
            comments
        ]

        self.ws.append_row(
            values,
            value_input_option="USER_ENTERED"
        )

        self.message = f'Current observation log is updated.'


#obslog = obslog()
#gc=gspread.service_account()
#sh=gc.open("LOGtest")
