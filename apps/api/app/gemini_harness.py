"""Native Gemini CLI command, pinned for reproducible runs."""

GEMINI_VERSION = "0.60.0"
GEMINI_PACKAGE = f"@google/gemini-cli@{GEMINI_VERSION}"


def gemini_command(model: str | None, prompt: str) -> list[str]:
    # Modal supplies the isolation; native tools run without interactive approvals.
    command = [
        "gemini",
        "--prompt",
        prompt,
        "--output-format",
        "stream-json",
        "--approval-mode",
        "yolo",
        # This workspace is freshly created by us inside an isolated sandbox.
        "--skip-trust",
    ]
    if model:
        command.extend(["--model", model])
    return command
