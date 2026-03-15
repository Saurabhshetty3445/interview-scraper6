"""
storage.py — CSV storage + Google Sheets push.

Google Sheets init failure is non-fatal — scraper keeps running
and saving to CSV even if Sheets auth fails (e.g. Railway network limits).
"""

import csv
import json
import logging
from pathlib import Path
from typing import Dict, Any

from config import (
    DATA_CSV_FILE,
    ENABLE_GOOGLE_SHEETS,
    GOOGLE_SHEETS_SPREADSHEET_ID,
    GOOGLE_SHEETS_WORKSHEET_NAME,
    GOOGLE_SHEETS_CREDENTIALS_JSON,
)

logger = logging.getLogger("scraper.storage")

CSV_COLUMNS = ["company", "title", "url", "date", "content_hash"]


class Storage:
    def __init__(self):
        self._csv_path = Path(DATA_CSV_FILE)
        self._ensure_csv_header()
        self._ws = None
        if ENABLE_GOOGLE_SHEETS:
            try:
                self._ws = self._init_sheets()
            except Exception as e:
                logger.error(f"Google Sheets init failed (non-fatal): {e}")
                logger.warning("Scraper will continue — saving to CSV only.")

    # ── CSV ────────────────────────────────────────────────────────────────────

    def _ensure_csv_header(self):
        if not self._csv_path.exists():
            with open(self._csv_path, "w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=CSV_COLUMNS).writeheader()
            logger.info("Created data.csv with header.")

    def _append_csv(self, record: Dict[str, Any]):
        row = {col: record.get(col, "") for col in CSV_COLUMNS}
        with open(self._csv_path, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_COLUMNS).writerow(row)

    # ── Google Sheets ──────────────────────────────────────────────────────────

    def _init_sheets(self):
        import gspread
        from google.oauth2.service_account import Credentials

        creds_json = GOOGLE_SHEETS_CREDENTIALS_JSON
        if not creds_json:
            logger.warning("GOOGLE_SHEETS_CREDENTIALS not set — Sheets disabled.")
            return None

        sheet_id = GOOGLE_SHEETS_SPREADSHEET_ID
        if not sheet_id:
            logger.warning("GOOGLE_SHEETS_ID not set — Sheets disabled.")
            return None

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(sheet_id)
        ws = sheet.worksheet(GOOGLE_SHEETS_WORKSHEET_NAME)
        logger.info(f"Google Sheets connected — '{GOOGLE_SHEETS_WORKSHEET_NAME}'")
        return ws

    def _append_sheets(self, record: Dict[str, Any]):
        if not self._ws:
            return
        row = [record.get(col, "") for col in CSV_COLUMNS]
        try:
            self._ws.append_row(row, value_input_option="USER_ENTERED")
            logger.info(
                f"Google Sheets updated — "
                f"{record.get('company')} | {record.get('title','')[:50]}"
            )
        except Exception as e:
            logger.error(f"Google Sheets append failed: {e}")

    # ── Public ─────────────────────────────────────────────────────────────────

    def save(self, record: Dict[str, Any]):
        self._append_csv(record)
        self._append_sheets(record)
