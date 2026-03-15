"""
config.py — Central configuration. All values can be overridden
by environment variables set in Railway dashboard.
"""

import os

# ── API ────────────────────────────────────────────────────────────────────────
GRAPHQL_URL = "https://leetcode.com/graphql"

# ── Relevance filter ───────────────────────────────────────────────────────────
TARGET_PHRASES = [
    "interview question",
    "interview questions",
    "interview experience",
    "interview experiences",
]

# ── Request behaviour ──────────────────────────────────────────────────────────
REQUEST_TIMEOUT   = 20
MIN_DELAY         = 2.0
MAX_DELAY         = 7.0
MAX_RETRIES       = 4
BACKOFF_BASE      = 2.5
MONITOR_PAGE_SIZE = 50

# ── Polling interval (minutes) ─────────────────────────────────────────────────
# Override via POLL_INTERVAL_MINUTES env var in Railway
POLL_INTERVAL_MINUTES = int(os.environ.get("POLL_INTERVAL_MINUTES", "30"))

# ── Deduplication ──────────────────────────────────────────────────────────────
FUZZY_THRESHOLD = 0.85

# ── File paths ─────────────────────────────────────────────────────────────────
DATA_CSV_FILE       = "data.csv"
PROCESSED_IDS_FILE  = "processed_ids.txt"
HASHES_FILE         = "hashes.txt"
QUEUE_FILE          = "queue.json"

# ── Google Sheets ──────────────────────────────────────────────────────────────
# Set these in Railway → Variables
ENABLE_GOOGLE_SHEETS             = True
GOOGLE_SHEETS_SPREADSHEET_ID     = os.environ.get("GOOGLE_SHEETS_ID", "")
GOOGLE_SHEETS_WORKSHEET_NAME     = os.environ.get("GOOGLE_SHEETS_WORKSHEET", "Sheet1")
GOOGLE_SHEETS_CREDENTIALS_JSON   = os.environ.get("GOOGLE_SHEETS_CREDENTIALS", "")

# ── Rotating User-Agent pool ───────────────────────────────────────────────────
HEADERS_POOL = [
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "Origin": "https://leetcode.com",
        "Referer": "https://leetcode.com/discuss/interview-experience/",
    },
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.0 Safari/605.1.15"
        ),
        "Accept": "application/json",
        "Accept-Language": "en-GB,en;q=0.8",
        "Content-Type": "application/json",
        "Origin": "https://leetcode.com",
        "Referer": "https://leetcode.com/discuss/",
    },
    {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) "
            "Gecko/20100101 Firefox/125.0"
        ),
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.7",
        "Content-Type": "application/json",
        "Origin": "https://leetcode.com",
        "Referer": "https://leetcode.com/discuss/interview-experience/",
    },
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0"
        ),
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "Origin": "https://leetcode.com",
        "Referer": "https://leetcode.com/discuss/",
    },
]

# ── Known company list ─────────────────────────────────────────────────────────
KNOWN_COMPANIES = [
    "Google","Meta","Facebook","Amazon","Apple","Microsoft","Netflix",
    "Nvidia","OpenAI","Anthropic","DeepMind","Tesla",
    "Oracle","SAP","IBM","Cisco","VMware","Salesforce","ServiceNow",
    "Workday","Databricks","Snowflake","Palantir","Cloudflare",
    "Goldman Sachs","JP Morgan","Morgan Stanley","BlackRock","Citadel",
    "Jane Street","Two Sigma","D.E. Shaw","Bloomberg","Stripe","Square",
    "PayPal","Visa","Mastercard","Robinhood","Coinbase",
    "Uber","Lyft","Airbnb","DoorDash","Instacart","Snapchat","Spotify",
    "Twitter","LinkedIn","Pinterest","Reddit","Dropbox","Box",
    "Zoom","Slack","Atlassian","Twilio","MongoDB","Elastic",
    "HashiCorp","Confluent","Datadog","New Relic","PagerDuty",
    "Flipkart","Swiggy","Zomato","Paytm","Byju","Meesho",
    "Razorpay","Cred","PhonePe","Ola","Freshworks","Zoho",
    "Infosys","TCS","Wipro","HCL","Tech Mahindra",
    "Adobe","Intuit","Qualcomm","Broadcom","Intel","AMD",
    "Roblox","Epic Games","Unity","ByteDance","TikTok",
    "Baidu","Alibaba","Tencent","Huawei","Samsung",
    "Booking.com","Expedia","eBay","Shopify","Wayfair",
]
