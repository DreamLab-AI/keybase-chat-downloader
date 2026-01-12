#!/usr/bin/env python3
"""Quick script to download btcresearch#ChartFu with WebP conversion."""

from pathlib import Path
from keybase_chat import KeybaseChat, download_chat_with_attachments

client = KeybaseChat()

# Create a mock conversation object for btcresearch#ChartFu
conv = {
    "channel": {
        "name": "btcresearch",
        "members_type": "team",
        "topic_name": "ChartFu",
    }
}

output_dir = Path("keybase_export_btcresearch_ChartFu")
download_chat_with_attachments(client, conv, output_dir, auto_download_attachments=True)
