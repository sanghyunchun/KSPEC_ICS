"""CMDLOG columns on new and existing observing-night worksheets."""

from unittest.mock import MagicMock, patch

from gspread import WorksheetNotFound

from Lib.updatelog import CMDLOG_HEADERS, obslog


def test_new_cmdlog_sheet_has_file_and_grating_columns():
    sheet = MagicMock()
    worksheet = sheet.add_worksheet.return_value
    with patch('Lib.updatelog.gspread.service_account') as account, \
            patch('Lib.updatelog.format_cell_range'):
        account.return_value.open.return_value = sheet
        sheet.worksheet.side_effect = WorksheetNotFound
        log = obslog('20261101')

    assert log.ws is worksheet
    assert sheet.add_worksheet.call_args.kwargs['cols'] == 11
    worksheet.update.assert_called_once_with([CMDLOG_HEADERS], range_name='A1:K1')
    assert worksheet.merge_cells.call_count == 11
    log.add_log('UT', 'P1', '0001', 'Object', 'target', 300, 3, '',
                'a.fits, b.fits, c.fits', '600', 430.0, value_input_option='RAW')
    assert worksheet.append_row.call_args.args[0][7:] == [
        'a.fits, b.fits, c.fits', '600', 430.0, '']


def test_existing_cmdlog_sheet_gains_columns_once():
    sheet = MagicMock()
    worksheet = sheet.worksheet.return_value
    worksheet.col_count = 8
    worksheet.row_values.return_value = CMDLOG_HEADERS[:7] + ['Comments']
    with patch('Lib.updatelog.gspread.service_account') as account, \
            patch('Lib.updatelog.format_cell_range'):
        account.return_value.open.return_value = sheet
        obslog('20261101')

    sheet.batch_update.assert_called_once_with({'requests': [{'insertDimension': {
        'range': {'sheetId': worksheet.id, 'dimension': 'COLUMNS',
                  'startIndex': 7, 'endIndex': 10},
        'inheritFromBefore': False,
    }}]})
    worksheet.update.assert_called_once_with([CMDLOG_HEADERS[7:]], range_name='H1:K1')
    assert worksheet.merge_cells.call_count == 3
    worksheet.resize.assert_not_called()

    worksheet.reset_mock()
    sheet.batch_update.reset_mock()
    worksheet.col_count = 11
    worksheet.row_values.return_value = CMDLOG_HEADERS
    with patch('Lib.updatelog.gspread.service_account') as account:
        account.return_value.open.return_value = sheet
        obslog('20261101')
    sheet.batch_update.assert_not_called()
    worksheet.resize.assert_not_called()
    worksheet.merge_cells.assert_not_called()
    worksheet.update.assert_not_called()
