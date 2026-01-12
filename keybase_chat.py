#!/usr/bin/env python3
"""
Keybase Chat Downloader

An interactive tool for downloading complete chat histories with attachments from Keybase.
Images are automatically converted to optimized WebP format.
Videos are re-encoded to efficient H.265/HEVC format.
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.prompt import Prompt, IntPrompt, Confirm
from rich.table import Table

load_dotenv()

console = Console()

# Image extensions that should be converted to WebP
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif"}
WEBP_QUALITY = 80  # Quality setting for WebP compression (0-100)

# Video extensions that should be re-encoded
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".wmv", ".flv"}
VIDEO_CRF = 28  # Constant Rate Factor for H.265 (18-28 is good, higher = smaller file)


class KeybaseChat:
    """Wrapper for Keybase chat API."""

    def _run_api(self, request: dict, timeout: int = 120) -> dict:
        """Execute a Keybase chat API request."""
        try:
            result = subprocess.run(
                ["keybase", "chat", "api", "-m", json.dumps(request)],
                capture_output=True,
                text=True,
                timeout=timeout,
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

    def list_conversations(self, limit: int = 100) -> list[dict]:
        """List recent conversations."""
        request = {
            "method": "list",
            "params": {"options": {"topic_type": "CHAT"}},
        }
        response = self._run_api(request)
        if "error" in response:
            console.print(f"[red]Error: {response['error'].get('message', 'Unknown error')}[/red]")
            return []

        conversations = response.get("result", {}).get("conversations", [])
        return conversations[:limit]

    def download_all_messages(self, channel: dict, batch_size: int = 1000) -> list[dict]:
        """Download all messages from a conversation using pagination."""
        all_messages = []
        pagination_next = None
        page = 1

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]Downloading messages...", total=None)

            while True:
                progress.update(task, description=f"[cyan]Fetching page {page}...")

                options: dict[str, Any] = {
                    "channel": channel,
                    "pagination": {"num": batch_size},
                    "peek": True,
                }

                if pagination_next:
                    options["pagination"]["next"] = pagination_next

                request = {"method": "read", "params": {"options": options}}
                response = self._run_api(request)

                if "error" in response:
                    console.print(f"[red]Error: {response['error'].get('message', 'Unknown error')}[/red]")
                    break

                result = response.get("result", {})
                messages = result.get("messages", [])
                pagination = result.get("pagination", {})

                all_messages.extend(messages)
                progress.update(task, description=f"[cyan]Page {page}: {len(all_messages)} messages total")

                is_last = pagination.get("last")
                if is_last is True or not messages:
                    break

                pagination_next = pagination.get("next")
                if not pagination_next:
                    break

                page += 1

        return all_messages

    def download_attachment(self, channel: dict, message_id: int, output_path: str) -> bool:
        """Download a single attachment."""
        request = {
            "method": "download",
            "params": {
                "options": {
                    "channel": channel,
                    "message_id": message_id,
                    "output": output_path,
                }
            },
        }
        response = self._run_api(request, timeout=300)
        return "error" not in response


def convert_to_webp(input_path: Path, quality: int = WEBP_QUALITY) -> Path | None:
    """
    Convert an image to WebP format using ImageMagick.
    Returns the new path if successful, None if conversion failed or not an image.
    """
    if input_path.suffix.lower() not in IMAGE_EXTENSIONS:
        return None

    output_path = input_path.with_suffix(".webp")

    try:
        result = subprocess.run(
            [
                "magick",
                str(input_path),
                "-quality", str(quality),
                "-define", "webp:lossless=false",
                "-define", f"webp:method=6",  # Highest compression method
                str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode == 0 and output_path.exists():
            # Remove original file
            input_path.unlink()
            return output_path
        else:
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def compress_video(input_path: Path, crf: int = VIDEO_CRF) -> Path | None:
    """
    Re-encode a video to H.265/HEVC format using ffmpeg for better compression.
    Returns the new path if successful, None if conversion failed or not a video.
    """
    if input_path.suffix.lower() not in VIDEO_EXTENSIONS:
        return None

    output_path = input_path.with_suffix(".mp4")
    temp_output = input_path.with_suffix(".h265.mp4")

    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-i", str(input_path),
                "-c:v", "libx265",
                "-crf", str(crf),
                "-preset", "medium",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                "-y",
                str(temp_output),
            ],
            capture_output=True,
            text=True,
            timeout=600,  # 10 min timeout for videos
        )

        if result.returncode == 0 and temp_output.exists():
            # Remove original and rename temp
            input_path.unlink()
            if output_path != input_path and output_path.exists():
                output_path.unlink()
            temp_output.rename(output_path)
            return output_path
        else:
            # Clean up temp file on failure
            if temp_output.exists():
                temp_output.unlink()
            return None
    except subprocess.TimeoutExpired:
        if temp_output.exists():
            temp_output.unlink()
        return None
    except FileNotFoundError:
        return None


def format_timestamp(ts: int | float | None) -> str:
    """Format a Unix timestamp to a readable string."""
    if not ts:
        return "Unknown"
    try:
        dt = datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError):
        return "Unknown"


def get_channel_from_conversation(conv: dict) -> dict:
    """Extract channel info from a conversation object."""
    channel = conv.get("channel", {})
    result = {"name": channel.get("name", "")}

    members_type = channel.get("members_type")
    if members_type == "team":
        result["members_type"] = "team"
        topic_name = channel.get("topic_name")
        if topic_name:
            result["topic_name"] = topic_name

    return result


def get_conversation_display_name(conv: dict) -> str:
    """Get a display name for a conversation."""
    channel = conv.get("channel", {})
    name = channel.get("name", "Unknown")
    members_type = channel.get("members_type", "user")
    topic_name = channel.get("topic_name")

    if members_type == "team" and topic_name:
        return f"{name}#{topic_name}"
    return name


def display_conversations(conversations: list[dict]) -> None:
    """Display a table of conversations."""
    table = Table(title="Available Conversations", show_header=True, header_style="bold magenta")
    table.add_column("#", style="cyan", width=4)
    table.add_column("Conversation", style="green")
    table.add_column("Type", style="yellow", width=10)
    table.add_column("Last Activity", style="dim")

    for i, conv in enumerate(conversations, 1):
        channel = conv.get("channel", {})
        name = channel.get("name", "Unknown")
        members_type = channel.get("members_type", "user")
        topic_name = channel.get("topic_name")

        display_name = f"{name}#{topic_name}" if members_type == "team" and topic_name else name

        active_at = conv.get("active_at")
        last_activity = format_timestamp(active_at) if active_at else "-"

        table.add_row(
            str(i),
            display_name[:50] + "..." if len(display_name) > 50 else display_name,
            members_type,
            last_activity,
        )

    console.print(table)


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

    sent_at = msg_data.get("sent_at")
    if sent_at:
        try:
            dt = datetime.fromtimestamp(sent_at)
            formatted["sent_at_human"] = dt.isoformat()
        except (ValueError, OSError):
            pass

    if msg_type == "text":
        formatted["body"] = content.get("text", {}).get("body", "")
        if "replyTo" in content.get("text", {}):
            formatted["reply_to"] = content["text"]["replyTo"]
    elif msg_type == "attachment":
        attachment = content.get("attachment", {})
        obj = attachment.get("object", {})
        formatted["body"] = obj.get("title", "")
        formatted["filename"] = obj.get("filename")
        formatted["mime_type"] = obj.get("mimeType")
        formatted["size"] = obj.get("size")
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

    return formatted


def get_attachment_filename(fmt_msg: dict) -> str:
    """Generate the attachment filename from message data."""
    msg_id = fmt_msg.get("id")
    original_filename = fmt_msg.get("filename", "unknown")
    sender = fmt_msg.get("sender", "unknown")
    sent_at = fmt_msg.get("sent_at")

    timestamp = ""
    if sent_at:
        try:
            dt = datetime.fromtimestamp(sent_at)
            timestamp = dt.strftime("%Y%m%d_%H%M%S")
        except (ValueError, OSError):
            timestamp = str(sent_at)

    safe_filename = "".join(
        c if c.isalnum() or c in "._-" else "_"
        for c in original_filename
    )
    return f"{msg_id}_{timestamp}_{sender}_{safe_filename}"


def download_chat_with_attachments(
    client: KeybaseChat,
    conv: dict,
    output_dir: Path,
    auto_download_attachments: bool = False,
) -> None:
    """Download complete chat history with all attachments."""
    channel = get_channel_from_conversation(conv)
    display_name = get_conversation_display_name(conv)

    console.print(f"\n[bold]Downloading: {display_name}[/bold]")
    console.print(f"Output directory: {output_dir}")
    console.print("=" * 60)

    # Create output directories
    output_dir.mkdir(parents=True, exist_ok=True)
    attachments_dir = output_dir / "attachments"
    attachments_dir.mkdir(exist_ok=True)

    # Download all messages
    messages = client.download_all_messages(channel)

    if not messages:
        console.print("[yellow]No messages found.[/yellow]")
        return

    console.print(f"[green]Downloaded {len(messages)} messages[/green]")

    # Sort chronologically
    messages.sort(key=lambda m: m.get("msg", {}).get("id", 0))

    # Format messages
    formatted_messages = [format_message(m) for m in messages]

    # Find attachments
    attachments = [
        (m, fm) for m, fm in zip(messages, formatted_messages)
        if fm.get("type") == "attachment"
    ]

    console.print(f"\n[bold]Found {len(attachments)} attachments to download[/bold]")

    # Track filename mappings for WebP conversion
    filename_map: dict[str, str] = {}  # original -> webp filename

    should_download = auto_download_attachments or Confirm.ask("Download all attachments?", default=True)
    if attachments and should_download:
        filename_map = download_attachments(client, channel, attachments, attachments_dir)

    # Update formatted messages with WebP filenames
    for fmt_msg in formatted_messages:
        if fmt_msg.get("type") == "attachment":
            original_name = get_attachment_filename(fmt_msg)
            if original_name in filename_map:
                fmt_msg["webp_filename"] = filename_map[original_name]
                fmt_msg["mime_type"] = "image/webp"

    # Save raw JSON
    raw_file = output_dir / "messages_raw.json"
    with open(raw_file, "w") as f:
        json.dump(messages, f, indent=2)
    console.print(f"Raw messages saved to: {raw_file}")

    # Save formatted JSON (with updated WebP filenames)
    formatted_file = output_dir / "messages_formatted.json"
    with open(formatted_file, "w") as f:
        json.dump(formatted_messages, f, indent=2)
    console.print(f"Formatted messages saved to: {formatted_file}")

    # Generate readable transcript with image links
    generate_transcript(formatted_messages, attachments_dir, output_dir, display_name, filename_map)

    # Print statistics
    print_statistics(formatted_messages, filename_map)


def download_attachments(
    client: KeybaseChat,
    channel: dict,
    attachments: list[tuple[dict, dict]],
    attachments_dir: Path,
) -> dict[str, str]:
    """
    Download all attachments with progress, converting images to WebP and videos to H.265.
    Returns a mapping of original filenames to converted filenames.
    """
    success_count = 0
    fail_count = 0
    skip_count = 0
    image_converted_count = 0
    video_converted_count = 0
    filename_map: dict[str, str] = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Downloading attachments...", total=len(attachments))

        for raw_msg, fmt_msg in attachments:
            msg_id = fmt_msg.get("id")
            output_filename = get_attachment_filename(fmt_msg)
            output_path = attachments_dir / output_filename
            suffix_lower = output_path.suffix.lower()

            # Check if already exists (converted versions)
            webp_path = output_path.with_suffix(".webp")
            h265_path = output_path.with_suffix(".mp4")

            if suffix_lower in IMAGE_EXTENSIONS and webp_path.exists():
                filename_map[output_filename] = webp_path.name
                skip_count += 1
                progress.advance(task)
                continue
            if suffix_lower in VIDEO_EXTENSIONS and h265_path.exists() and h265_path != output_path:
                filename_map[output_filename] = h265_path.name
                skip_count += 1
                progress.advance(task)
                continue
            if output_path.exists():
                # File exists but not converted - try to convert now
                new_path = convert_to_webp(output_path)
                if new_path:
                    filename_map[output_filename] = new_path.name
                    image_converted_count += 1
                else:
                    new_path = compress_video(output_path)
                    if new_path:
                        filename_map[output_filename] = new_path.name
                        video_converted_count += 1
                skip_count += 1
                progress.advance(task)
                continue

            progress.update(task, description=f"[cyan]{output_filename[:40]}...")

            if client.download_attachment(channel, msg_id, str(output_path)):
                success_count += 1

                # Convert to WebP if it's an image
                new_path = convert_to_webp(output_path)
                if new_path:
                    filename_map[output_filename] = new_path.name
                    image_converted_count += 1
                else:
                    # Compress video if it's a video
                    new_path = compress_video(output_path)
                    if new_path:
                        filename_map[output_filename] = new_path.name
                        video_converted_count += 1
            else:
                fail_count += 1

            progress.advance(task)

    console.print(f"\n[green]Attachments: {success_count} downloaded, {skip_count} skipped, {fail_count} failed[/green]")
    console.print(f"[green]Images converted to WebP: {image_converted_count}[/green]")
    console.print(f"[green]Videos compressed to H.265: {video_converted_count}[/green]")

    return filename_map


def generate_transcript(
    messages: list[dict],
    attachments_dir: Path,
    output_dir: Path,
    display_name: str,
    filename_map: dict[str, str],
) -> None:
    """Generate a readable transcript with linked images."""
    # Generate markdown transcript
    md_file = output_dir / "transcript.md"
    with open(md_file, "w") as f:
        f.write(f"# Chat History: {display_name}\n\n")
        f.write(f"Downloaded: {datetime.now().isoformat()}\n\n")
        f.write(f"Total messages: {len(messages)}\n\n")
        f.write("---\n\n")

        for msg in messages:
            msg_type = msg.get("type")
            if msg_type not in ("text", "attachment"):
                continue

            timestamp = msg.get("sent_at_human", "Unknown time")
            sender = msg.get("sender", "Unknown")
            body = msg.get("body", "")

            f.write(f"**{sender}** _{timestamp}_\n\n")

            if msg_type == "attachment":
                original_filename = get_attachment_filename(msg)

                # Use WebP filename if available, otherwise original
                if original_filename in filename_map:
                    attachment_filename = filename_map[original_filename]
                elif msg.get("webp_filename"):
                    attachment_filename = msg["webp_filename"]
                else:
                    attachment_filename = original_filename

                attachment_path = f"attachments/{attachment_filename}"

                mime_type = msg.get("mime_type", "")
                if mime_type and mime_type.startswith("image/"):
                    f.write(f"![{body or attachment_filename}]({attachment_path})\n\n")
                else:
                    f.write(f"[{body or attachment_filename}]({attachment_path})\n\n")

            if body and msg_type == "text":
                f.write(f"{body}\n\n")

            f.write("---\n\n")

    console.print(f"Markdown transcript saved to: {md_file}")

    # Generate plain text transcript
    txt_file = output_dir / "transcript.txt"
    with open(txt_file, "w") as f:
        f.write(f"Chat History: {display_name}\n")
        f.write(f"Downloaded: {datetime.now().isoformat()}\n")
        f.write(f"Total messages: {len(messages)}\n")
        f.write("=" * 60 + "\n\n")

        for msg in messages:
            msg_type = msg.get("type")
            if msg_type not in ("text", "attachment"):
                continue

            timestamp = msg.get("sent_at_human", "Unknown time")
            sender = msg.get("sender", "Unknown")
            body = msg.get("body", "")

            f.write(f"[{timestamp}] {sender}:\n")

            if msg_type == "attachment":
                original_filename = get_attachment_filename(msg)
                if original_filename in filename_map:
                    filename = filename_map[original_filename]
                elif msg.get("webp_filename"):
                    filename = msg["webp_filename"]
                else:
                    filename = msg.get("filename", "file")
                f.write(f"  [Attachment: {filename}]\n")

            if body:
                f.write(f"  {body}\n")

            f.write("\n")

    console.print(f"Text transcript saved to: {txt_file}")


def print_statistics(messages: list[dict], filename_map: dict[str, str]) -> None:
    """Print message statistics."""
    text_count = sum(1 for m in messages if m.get("type") == "text")
    attachment_count = sum(1 for m in messages if m.get("type") == "attachment")
    reaction_count = sum(1 for m in messages if m.get("type") == "reaction")
    webp_count = len(filename_map)

    senders = {}
    for m in messages:
        sender = m.get("sender")
        if sender:
            senders[sender] = senders.get(sender, 0) + 1

    console.print("\n[bold]Statistics:[/bold]")
    console.print(f"  Text messages: {text_count}")
    console.print(f"  Attachments: {attachment_count}")
    console.print(f"  Images converted to WebP: {webp_count}")
    console.print(f"  Reactions: {reaction_count}")
    console.print(f"  Unique participants: {len(senders)}")

    # Show top 10 participants
    sorted_senders = sorted(senders.items(), key=lambda x: x[1], reverse=True)[:10]
    for sender, count in sorted_senders:
        console.print(f"    - {sender}: {count}")


def interactive_menu() -> None:
    """Run the interactive menu."""
    client = KeybaseChat()
    conversations: list[dict] = []

    console.print(Panel.fit(
        "[bold blue]Keybase Chat Downloader[/bold blue]\n"
        "Download complete chat histories with attachments\n"
        "[dim]Images auto-converted to optimized WebP[/dim]",
        border_style="blue",
    ))

    while True:
        console.print()
        console.print("[bold]Commands:[/bold]")
        console.print("  [cyan]1[/cyan] - List conversations")
        console.print("  [cyan]2[/cyan] - Download a conversation (with attachments)")
        console.print("  [cyan]3[/cyan] - Download multiple conversations")
        console.print("  [cyan]q[/cyan] - Quit")
        console.print()

        choice = Prompt.ask("Select option", choices=["1", "2", "3", "q"], default="1")

        if choice == "q":
            console.print("[yellow]Goodbye![/yellow]")
            break

        elif choice == "1":
            limit = IntPrompt.ask("How many conversations to list?", default=50)
            with console.status("[bold green]Fetching conversations..."):
                conversations = client.list_conversations(limit=limit)
            if conversations:
                display_conversations(conversations)
            else:
                console.print("[yellow]No conversations found.[/yellow]")

        elif choice == "2":
            if not conversations:
                console.print("[yellow]Fetching conversations first...[/yellow]")
                with console.status("[bold green]Fetching conversations..."):
                    conversations = client.list_conversations(limit=50)
                if conversations:
                    display_conversations(conversations)
                else:
                    console.print("[yellow]No conversations found.[/yellow]")
                    continue

            display_conversations(conversations)
            conv_num = IntPrompt.ask("Enter conversation number to download", default=1)

            if conv_num < 1 or conv_num > len(conversations):
                console.print("[red]Invalid conversation number.[/red]")
                continue

            conv = conversations[conv_num - 1]
            display_name = get_conversation_display_name(conv)

            # Generate output directory name
            safe_name = "".join(
                c if c.isalnum() or c in "._-" else "_"
                for c in display_name
            )
            default_dir = f"keybase_export_{safe_name}"
            output_dir = Prompt.ask("Output directory", default=default_dir)

            download_chat_with_attachments(client, conv, Path(output_dir))

        elif choice == "3":
            if not conversations:
                console.print("[yellow]Fetching conversations first...[/yellow]")
                with console.status("[bold green]Fetching conversations..."):
                    conversations = client.list_conversations(limit=50)
                if conversations:
                    display_conversations(conversations)
                else:
                    console.print("[yellow]No conversations found.[/yellow]")
                    continue

            display_conversations(conversations)
            selection = Prompt.ask(
                "Enter conversation numbers (comma-separated, e.g., 1,3,5)",
                default="1",
            )

            try:
                numbers = [int(n.strip()) for n in selection.split(",")]
            except ValueError:
                console.print("[red]Invalid input. Please enter numbers separated by commas.[/red]")
                continue

            for num in numbers:
                if num < 1 or num > len(conversations):
                    console.print(f"[red]Skipping invalid number: {num}[/red]")
                    continue

                conv = conversations[num - 1]
                display_name = get_conversation_display_name(conv)
                safe_name = "".join(
                    c if c.isalnum() or c in "._-" else "_"
                    for c in display_name
                )
                output_dir = Path(f"keybase_export_{safe_name}")

                download_chat_with_attachments(client, conv, output_dir)


def main():
    """Main entry point."""
    try:
        result = subprocess.run(
            ["keybase", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if "Logged in:     yes" not in result.stdout:
            console.print("[red]Error: Not logged into Keybase.[/red]")
            console.print("Please run 'keybase login' first.")
            sys.exit(1)
    except FileNotFoundError:
        console.print("[red]Error: Keybase CLI not found.[/red]")
        console.print("Please install Keybase: https://keybase.io/download")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        console.print("[yellow]Warning: Keybase status check timed out, proceeding anyway...[/yellow]")

    interactive_menu()


if __name__ == "__main__":
    main()
