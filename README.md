# Keybase Chat Downloader

An interactive Python tool for downloading complete chat histories from Keybase, with automatic media optimization.

## Features

- **Interactive conversation browser** - List and select from all your Keybase conversations (DMs and team channels)
- **Complete history download** - Fetches entire chat history with pagination support
- **Attachment handling** - Downloads all attachments (images, videos, files, etc.)
- **WebP optimization** - Automatically converts images to optimized WebP format
- **Video compression** - Re-encodes videos to efficient H.265/HEVC format
- **Multiple export formats**:
  - `messages_raw.json` - Full API response data
  - `messages_formatted.json` - Cleaned/structured message data with converted filenames
  - `transcript.md` - Markdown transcript with embedded images
  - `transcript.txt` - Plain text transcript

## Requirements

- Python 3.10+
- [Keybase CLI](https://keybase.io/download) installed and logged in
- ImageMagick 7+ (for WebP conversion)
- ffmpeg (for video compression)

## Installation

```bash
# Clone the repository
git clone https://github.com/dreamlab-ai/keybase-chat-downloader.git
cd keybase-chat-downloader

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or venv/bin/activate.fish for fish shell

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Interactive Mode

```bash
python keybase_chat.py
```

This launches an interactive menu where you can:

1. List all conversations
2. Download a single conversation with attachments
3. Download multiple conversations at once

### Programmatic Usage

```python
from pathlib import Path
from keybase_chat import KeybaseChat, download_chat_with_attachments

client = KeybaseChat()

# Download a team channel
conv = {
    "channel": {
        "name": "myteam",
        "members_type": "team",
        "topic_name": "general",
    }
}
download_chat_with_attachments(client, conv, Path("export_dir"), auto_download_attachments=True)

# Download a DM
conv = {
    "channel": {
        "name": "username1,username2",
    }
}
download_chat_with_attachments(client, conv, Path("dm_export"), auto_download_attachments=True)
```

## Output Structure

```text
keybase_export_teamname_channel/
├── messages_raw.json        # Complete API response
├── messages_formatted.json  # Processed messages with converted filenames
├── transcript.md            # Markdown with embedded images
├── transcript.txt           # Plain text version
└── attachments/
    ├── 123_20210315_user_image.webp
    ├── 124_20210316_user_video.mp4
    └── ...
```

## Media Conversion

### Images

Images (PNG, JPG, JPEG, GIF, BMP, TIFF) are automatically converted to WebP format with:

- Quality: 80 (good balance of size/quality)
- Method: 6 (maximum compression)
- Original files are deleted after successful conversion

To adjust quality, modify `WEBP_QUALITY` in `keybase_chat.py`.

### Videos

Videos (MP4, MOV, AVI, MKV, WebM, M4V, WMV, FLV) are re-encoded to H.265/HEVC with:

- CRF: 28 (constant rate factor, lower = higher quality)
- Preset: medium (balance of speed/compression)
- Audio: AAC at 128k
- Original files are deleted after successful conversion

To adjust quality, modify `VIDEO_CRF` in `keybase_chat.py`.

## Configuration

Create a `.env` file for any environment-specific settings:

```bash
# .env (optional)
KEYBASE_PAPER_KEY="your-paper-key"  # Only if needed for automation
```

## License

MIT License

## Author

Dr John O'Hare
