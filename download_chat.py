#!/usr/bin/env python3
"""
Download complete chat history from a Keybase team channel.
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
            timeout=120,
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


def download_channel(team: str, topic: str, batch_size: int = 1000) -> list[dict]:
    """Download all messages from a team channel using pagination."""
    all_messages = []
    pagination_next = None
    page = 1

    while True:
        print(f"Fetching page {page}...", end=" ", flush=True)

        options = {
            "channel": {
                "name": team,
                "members_type": "team",
                "topic_name": topic,
            },
            "pagination": {"num": batch_size},
            "peek": True,
        }

        if pagination_next:
            options["pagination"]["next"] = pagination_next

        request = {"method": "read", "params": {"options": options}}
        response = run_api(request)

        if "error" in response:
            print(f"\nError: {response['error'].get('message', 'Unknown error')}")
            break

        result = response.get("result", {})
        messages = result.get("messages", [])
        pagination = result.get("pagination", {})

        all_messages.extend(messages)
        print(f"got {len(messages)} messages (total: {len(all_messages)})")

        # Check if we've reached the end
        is_last = pagination.get("last")
        if is_last is True or not messages:
            break

        pagination_next = pagination.get("next")
        if not pagination_next:
            break

        page += 1

    return all_messages


def format_message(msg: dict) -> dict:
    """Extract relevant fields from a message for export."""
    msg_data = msg.get("msg", {})
    content = msg_data.get("content", {})
    msg_type = content.get("type")

    formatted = {
        "id": msg_data.get("id"),
        "type": msg_type,
        "sender": msg_data.get("sender", {}).get("username"),
        "device": msg_data.get("sender", {}).get("device_name"),
        "sent_at": msg_data.get("sent_at"),
        "sent_at_human": None,
    }

    # Convert timestamp
    sent_at = msg_data.get("sent_at")
    if sent_at:
        try:
            dt = datetime.fromtimestamp(sent_at)
            formatted["sent_at_human"] = dt.isoformat()
        except (ValueError, OSError):
            pass

    # Extract content based on type
    if msg_type == "text":
        formatted["body"] = content.get("text", {}).get("body", "")
    elif msg_type == "attachment":
        attachment = content.get("attachment", {})
        obj = attachment.get("object", {})
        formatted["body"] = obj.get("title", "")
        formatted["filename"] = obj.get("filename")
        formatted["mime_type"] = obj.get("mimeType")
    elif msg_type == "edit":
        edit = content.get("edit", {})
        formatted["body"] = edit.get("body", "")
        formatted["edited_message_id"] = edit.get("messageID")
    elif msg_type == "reaction":
        reaction = content.get("reaction", {})
        formatted["body"] = reaction.get("b", "")
        formatted["reaction_to"] = reaction.get("m")
    elif msg_type == "system":
        system = content.get("system", {})
        formatted["system_type"] = system.get("systemType")
    elif msg_type == "delete":
        formatted["deleted_message_ids"] = content.get("delete", {}).get("messageIDs", [])

    # Include reply info if present
    reply_to = msg_data.get("content", {}).get("text", {})
    if "replyTo" in content.get("text", {}):
        formatted["reply_to"] = content["text"]["replyTo"]

    return formatted


def main():
    team = "btcresearch"
    topic = "ChartFu"

    print(f"Downloading chat history from {team}#{topic}...")
    print("=" * 60)

    messages = download_channel(team, topic)

    if not messages:
        print("No messages found.")
        return

    print("=" * 60)
    print(f"Total messages downloaded: {len(messages)}")

    # Sort by message ID (chronological order)
    messages.sort(key=lambda m: m.get("msg", {}).get("id", 0))

    # Save raw JSON
    raw_filename = f"{team}_{topic}_raw.json"
    with open(raw_filename, "w") as f:
        json.dump(messages, f, indent=2)
    print(f"Raw messages saved to: {raw_filename}")

    # Save formatted version
    formatted_messages = [format_message(m) for m in messages]
    formatted_filename = f"{team}_{topic}_formatted.json"
    with open(formatted_filename, "w") as f:
        json.dump(formatted_messages, f, indent=2)
    print(f"Formatted messages saved to: {formatted_filename}")

    # Save as readable text
    text_filename = f"{team}_{topic}_readable.txt"
    with open(text_filename, "w") as f:
        f.write(f"Chat History: {team}#{topic}\n")
        f.write(f"Downloaded: {datetime.now().isoformat()}\n")
        f.write(f"Total messages: {len(formatted_messages)}\n")
        f.write("=" * 60 + "\n\n")

        for msg in formatted_messages:
            if msg["type"] in ("text", "attachment"):
                timestamp = msg.get("sent_at_human", "Unknown time")
                sender = msg.get("sender", "Unknown")
                body = msg.get("body", "")

                f.write(f"[{timestamp}] {sender}:\n")
                if msg["type"] == "attachment":
                    f.write(f"  [Attachment: {msg.get('filename', 'file')}]\n")
                if body:
                    f.write(f"  {body}\n")
                f.write("\n")

    print(f"Readable transcript saved to: {text_filename}")

    # Stats
    text_count = sum(1 for m in formatted_messages if m["type"] == "text")
    attachment_count = sum(1 for m in formatted_messages if m["type"] == "attachment")
    reaction_count = sum(1 for m in formatted_messages if m["type"] == "reaction")

    print("\nMessage statistics:")
    print(f"  Text messages: {text_count}")
    print(f"  Attachments: {attachment_count}")
    print(f"  Reactions: {reaction_count}")

    # Get unique senders
    senders = set(m.get("sender") for m in formatted_messages if m.get("sender"))
    print(f"  Unique participants: {len(senders)}")
    for sender in sorted(senders):
        count = sum(1 for m in formatted_messages if m.get("sender") == sender)
        print(f"    - {sender}: {count} messages")


if __name__ == "__main__":
    main()
