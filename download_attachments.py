#!/usr/bin/env python3
"""
Download all attachments from a Keybase team channel chat.
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def run_api(request: dict) -> dict:
    """Execute a Keybase chat API request."""
    try:
        result = subprocess.run(
            ["keybase", "chat", "api", "-m", json.dumps(request)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            return {"error": {"message": result.stderr or "Unknown error"}}
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return {"error": {"message": "Request timed out"}}
    except json.JSONDecodeError as e:
        return {"error": {"message": f"Failed to parse response: {e}"}}
    except Exception as e:
        return {"error": {"message": str(e)}}


def download_attachment(
    team: str,
    topic: str,
    message_id: int,
    output_path: str,
) -> bool:
    """Download a single attachment."""
    request = {
        "method": "download",
        "params": {
            "options": {
                "channel": {
                    "name": team,
                    "members_type": "team",
                    "topic_name": topic,
                },
                "message_id": message_id,
                "output": output_path,
            }
        },
    }
    response = run_api(request)
    return "error" not in response


def main():
    team = "btcresearch"
    topic = "ChartFu"
    raw_file = "btcresearch_ChartFu_raw.json"

    # Create output directory
    output_dir = Path(f"{team}_{topic}_attachments")
    output_dir.mkdir(exist_ok=True)

    # Load messages
    print(f"Loading messages from {raw_file}...")
    with open(raw_file) as f:
        messages = json.load(f)

    # Find all attachments
    attachments = []
    for msg in messages:
        msg_data = msg.get("msg", {})
        content = msg_data.get("content", {})
        if content.get("type") == "attachment":
            att_info = content.get("attachment", {})
            obj = att_info.get("object", {})
            attachments.append({
                "message_id": msg_data.get("id"),
                "sender": msg_data.get("sender", {}).get("username"),
                "sent_at": msg_data.get("sent_at"),
                "filename": obj.get("filename", "unknown"),
                "title": obj.get("title", ""),
                "size": obj.get("size", 0),
                "mime_type": obj.get("mimeType", ""),
            })

    print(f"Found {len(attachments)} attachments")
    print(f"Output directory: {output_dir}")
    print("=" * 60)

    # Download each attachment
    success_count = 0
    fail_count = 0
    skip_count = 0

    for i, att in enumerate(attachments, 1):
        msg_id = att["message_id"]
        original_filename = att["filename"]
        sender = att["sender"]
        sent_at = att["sent_at"]

        # Create unique filename with message ID prefix
        timestamp = ""
        if sent_at:
            try:
                dt = datetime.fromtimestamp(sent_at)
                timestamp = dt.strftime("%Y%m%d_%H%M%S")
            except (ValueError, OSError):
                timestamp = str(sent_at)

        # Sanitize filename
        safe_filename = "".join(
            c if c.isalnum() or c in "._-" else "_"
            for c in original_filename
        )
        output_filename = f"{msg_id}_{timestamp}_{sender}_{safe_filename}"
        output_path = output_dir / output_filename

        # Skip if already downloaded
        if output_path.exists():
            print(f"[{i}/{len(attachments)}] Skipping (exists): {output_filename}")
            skip_count += 1
            continue

        print(f"[{i}/{len(attachments)}] Downloading: {output_filename}...", end=" ", flush=True)

        if download_attachment(team, topic, msg_id, str(output_path)):
            print("OK")
            success_count += 1
        else:
            print("FAILED")
            fail_count += 1

    print("=" * 60)
    print(f"Download complete!")
    print(f"  Success: {success_count}")
    print(f"  Skipped: {skip_count}")
    print(f"  Failed:  {fail_count}")
    print(f"  Total:   {len(attachments)}")

    # Save attachment metadata
    metadata_file = output_dir / "_attachments_metadata.json"
    with open(metadata_file, "w") as f:
        json.dump(attachments, f, indent=2)
    print(f"\nMetadata saved to: {metadata_file}")


if __name__ == "__main__":
    main()
