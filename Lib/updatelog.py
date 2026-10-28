import gspread
from gspread_formatting import *

CMDLOG_HEADERS = ['UT', 'PROJID', 'TILE ID', 'OBJTYPE', 'OBJECT', 'EXPOSURE',
                  'EXP #', 'File', 'grating', 'central wave', 'Comment']

class obslog():
    def __init__(self, dir_name):
        self.gc = gspread.service_account()
        self.sh = self.gc.open("CMDLOG")
        self.title = dir_name
        self.ws, self.created = self._get_or_create_worksheet()

        if self.created:
            self._setup_worksheet()
        else:
            self._upgrade_worksheet()

        self.message = f'{self.title} command log {"created" if self.created else "loaded"}'

    def _get_or_create_worksheet(self):
        try:
            return self.sh.worksheet(self.title), False
        except gspread.WorksheetNotFound:
            return self.sh.add_worksheet(
                title=self.title,
                rows=200,
                cols=len(CMDLOG_HEADERS),
                index=0
            ), True

    def _setup_worksheet(self):
        self.ws.freeze(rows=2)

        for col in range(1, len(CMDLOG_HEADERS) + 1):
            self.ws.merge_cells(1, col, 2, col)     # (row_start=1, col_start=col, row_end=2, col_end=col)

        self.ws.update([CMDLOG_HEADERS], range_name="A1:K1")

        self._format_headers("A1:K2")

    def _upgrade_worksheet(self):
        """Insert new fields before Comments without moving existing comment data."""
        headers = self.ws.row_values(1)
        if headers[7:11] == CMDLOG_HEADERS[7:11]:
            return
        if headers[7] != 'Comments':
            raise ValueError(f'Unexpected CMDLOG columns in {self.title}: {headers!r}')
        self.sh.batch_update({'requests': [{'insertDimension': {
            'range': {'sheetId': self.ws.id, 'dimension': 'COLUMNS',
                      'startIndex': 7, 'endIndex': 10},
            'inheritFromBefore': False,
        }}]})
        self.ws = self.sh.worksheet(self.title)  # refresh the worksheet's column count
        for col in range(8, 11):
            self.ws.merge_cells(1, col, 2, col)
        self.ws.update([CMDLOG_HEADERS[7:]], range_name="H1:K1")
        self._format_headers("H1:K2")

    def _format_headers(self, cell_range):
        fmt = CellFormat(
            textFormat=TextFormat(bold=True),       
            horizontalAlignment='CENTER',           
            verticalAlignment='MIDDLE'          
        )

        format_cell_range(self.ws, cell_range, fmt)


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
        file="",
        grating="",
        central_wave="",
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
            file,
            grating,
            central_wave,
            comments,
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
                row["object_name"], row["exposure"], row["exp_num"], row.get("comments", ""),
                row.get("file", ""), row.get("grating", ""), row.get("central_wave", ""),
                value_input_option="RAW")
    return log


#obslog = obslog()
#gc=gspread.service_account()
#sh=gc.open("LOGtest")
