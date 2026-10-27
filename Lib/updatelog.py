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
                cols=8,
                index=0
            ), True

    def _setup_worksheet(self):
        self.ws.freeze(rows=2)

        # Merge the two header rows in each of the eight CMDLOG columns.
        for col in range(1, 9):
            self.ws.merge_cells(1, col, 2, col)     # (row_start=1, col_start=col, row_end=2, col_end=col)

        letters = ['UT', 'PROJID', 'TILE ID', 'OBJTYPE', 'OBJECT', 'EXPOSURE', 'EXP #', 'Comments']
        self.ws.update([letters], range_name="A1:H1")

        fmt = CellFormat(
            textFormat=TextFormat(bold=True),       
            horizontalAlignment='CENTER',           
            verticalAlignment='MIDDLE'          
        )

        format_cell_range(self.ws, "A1:H2", fmt)


    def add_log(
        self,
        ut,
        projid,
        tile_id,
        objtype,
        object_name,
        exposure,
        exp_num,
        comments="",
        value_input_option="USER_ENTERED",
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
            value_input_option=value_input_option
        )

        self.message = f'Current observation log is updated.'


def add_isoplane_reply(current_log, reply):
    """Record a successful IsoPlane frame reply on the ICS and return the active worksheet."""
    if (reply.get("inst") != "SPEC" or reply.get("process") != "Done"
            or reply.get("status") != "success" or reply.get("backend") != "ISOPLANE"
            or not isinstance(reply.get("cmdlog"), dict)):
        return current_log

    row = reply["cmdlog"]
    night = row["night"]
    log = current_log if current_log is not None and current_log.title == night else obslog(night)
    log.add_log(row["ut"], row["projid"], row["tile_id"], row["objtype"],
                row["object_name"], row["exposure"], row["exp_num"], row["comments"],
                value_input_option="RAW")
    return log


#obslog = obslog()
#gc=gspread.service_account()
#sh=gc.open("LOGtest")
