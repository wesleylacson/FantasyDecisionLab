// Fantasy Decision Lab — Google Sheets projection sync bridge
// One-time setup: bind this script to the Fantasy Projection Tracker, choose a long
// random shared token below, deploy as a Web App executing as you, and configure the
// local workbench with the /exec URL + same token.

const FDL_SPREADSHEET_ID = '1JCsYfw2-9n8JXrjVa-1Rnclw1clHlvh4vwUvaCdiNGk';
const FDL_SHEET_NAME = 'Projection Tracker';
const FDL_SYNC_TOKEN = 'REPLACE_WITH_A_LONG_RANDOM_TOKEN';

function json_(value) {
  return ContentService.createTextOutput(JSON.stringify(value))
    .setMimeType(ContentService.MimeType.JSON);
}

function doGet() {
  return json_({ok: true, service: 'Fantasy Decision Lab projection sync'});
}

function doPost(e) {
  try {
    const body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    if (!FDL_SYNC_TOKEN || FDL_SYNC_TOKEN === 'REPLACE_WITH_A_LONG_RANDOM_TOKEN') {
      throw new Error('FDL_SYNC_TOKEN has not been configured in Apps Script.');
    }
    if (body.token !== FDL_SYNC_TOKEN) throw new Error('Unauthorized sync token.');
    if (body.action !== 'upsert_projection') throw new Error('Unsupported action.');
    return json_(upsertProjection_(body.tracker_key, body.record || {}));
  } catch (err) {
    return json_({ok: false, error: String(err && err.message ? err.message : err)});
  }
}

function headerMap_(sheet) {
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getDisplayValues()[0];
  const map = {};
  headers.forEach((h, i) => { if (h) map[h] = i + 1; });
  return map;
}

function cell_(record, name) {
  const v = record[name];
  return (v === undefined || v === null) ? '' : v;
}

function upsertProjection_(trackerKey, record) {
  if (!trackerKey) throw new Error('Missing projection key.');
  const ss = SpreadsheetApp.openById(FDL_SPREADSHEET_ID);
  const sheet = ss.getSheetByName(FDL_SHEET_NAME);
  if (!sheet) throw new Error('Projection Tracker sheet not found.');
  const h = headerMap_(sheet);
  ['Projection Key','Week','Workbench Revision','Locked','Generated At','Workbench Record ID'].forEach(name => {
    if (!h[name]) throw new Error('Missing tracker metadata column: ' + name);
  });

  const lastRow = Math.max(sheet.getLastRow(), 1);
  let row = null;
  if (lastRow >= 2) {
    const keys = sheet.getRange(2, h['Projection Key'], lastRow - 1, 1).getDisplayValues();
    for (let i = 0; i < keys.length; i++) {
      if (keys[i][0] === trackerKey) { row = i + 2; break; }
    }
  }

  let inserted = false;
  if (!row) {
    row = lastRow + 1;
    sheet.insertRowAfter(lastRow);
    inserted = true;
    // Carry the existing visual grammar forward without copying row-specific values.
    sheet.getRange(lastRow, 1, 1, sheet.getLastColumn())
      .copyTo(sheet.getRange(row, 1, 1, sheet.getLastColumn()), SpreadsheetApp.CopyPasteType.PASTE_FORMAT, false);
    if (h['Pass Att Err'] && h['App FP Err']) {
      sheet.getRange(lastRow, h['Pass Att Err'], 1, h['App FP Err'] - h['Pass Att Err'] + 1)
        .copyTo(sheet.getRange(row, h['Pass Att Err'], 1, h['App FP Err'] - h['Pass Att Err'] + 1), SpreadsheetApp.CopyPasteType.PASTE_FORMULA, false);
    }
  }

  // Once a provider actual is present, the original forecast is a historical benchmark.
  // Do not let a later accidental run rewrite its projection fields.
  if (h['Actual FP'] && sheet.getRange(row, h['Actual FP']).getValue() !== '' && cell_(record, 'actual_fp') === '') {
    return {ok: true, status: 'blocked_postgame', row: row, tracker_key: trackerKey};
  }

  const dateValue = String(cell_(record, 'created_at') || '').slice(0, 10);
  const projectionValues = [[
    dateValue,
    cell_(record, 'league'),
    cell_(record, 'player'),
    cell_(record, 'position'),
    cell_(record, 'opponent'),
    cell_(record, 'pass_attempts'),
    cell_(record, 'pass_yards'),
    cell_(record, 'pass_tds'),
    cell_(record, 'interceptions'),
    cell_(record, 'rush_attempts'),
    cell_(record, 'rush_yards'),
    cell_(record, 'rush_tds'),
    cell_(record, 'targets'),
    cell_(record, 'receptions'),
    cell_(record, 'rec_yards'),
    cell_(record, 'rec_tds'),
    cell_(record, 'first_downs'),
    cell_(record, 'projected_fp'),
    cell_(record, 'app_fp')
  ]];
  sheet.getRange(row, 1, 1, 19).setValues(projectionValues);

  sheet.getRange(row, h['Week']).setValue(cell_(record, 'week'));
  sheet.getRange(row, h['Projection Key']).setValue(trackerKey);
  sheet.getRange(row, h['Workbench Revision']).setValue(cell_(record, 'revision'));
  sheet.getRange(row, h['Locked']).setValue(Boolean(record.locked));
  sheet.getRange(row, h['Generated At']).setValue(cell_(record, 'created_at'));
  sheet.getRange(row, h['Workbench Record ID']).setValue(cell_(record, 'id'));

  // ESPN exposes useful component projections in addition to the headline fantasy-point total.
  // These fields are optional. Blank values remain blank; never back-solve hidden components.
  const appProjectionColumns = {
    'ESPN Proj Carries': 'app_carries',
    'ESPN Proj Receptions': 'app_receptions',
    'ESPN Proj Targets': 'app_targets',
    'ESPN Proj Pass Yds': 'app_pass_yards',
    'ESPN Proj Rush Yds': 'app_rush_yards',
    'ESPN Proj Rec Yds': 'app_rec_yards',
    'ESPN Proj Pass TD': 'app_pass_tds',
    'ESPN Proj Rush TD': 'app_rush_tds',
    'ESPN Proj Rec TD': 'app_rec_tds'
  };
  const isEspn = String(cell_(record, 'app_source') || 'espn').toLowerCase() === 'espn';
  Object.keys(appProjectionColumns).forEach(header => {
    if (!h[header]) return;
    const value = isEspn ? cell_(record, appProjectionColumns[header]) : '';
    sheet.getRange(row, h[header]).setValue(value);
  });

  // New rows can carry a concise model summary in Notes. Existing human/postmortem notes are
  // never overwritten; this keeps the tracker safe for later diagnosis.
  if (h['Notes'] && cell_(record, 'projection_summary')) {
    const notesCell = sheet.getRange(row, h['Notes']);
    const existing = String(notesCell.getValue() || '');
    if (!existing || existing.indexOf('[Workbench] ') === 0) {
      notesCell.setValue('[Workbench] ' + cell_(record, 'projection_summary'));
    }
  }

  // If grading happens in the workbench, allow the provider total to flow back too.
  if (h['Actual FP'] && cell_(record, 'actual_fp') !== '') {
    sheet.getRange(row, h['Actual FP']).setValue(cell_(record, 'actual_fp'));
  }

  SpreadsheetApp.flush();
  return {ok: true, status: inserted ? 'inserted' : 'updated', row: row, tracker_key: trackerKey};
}
