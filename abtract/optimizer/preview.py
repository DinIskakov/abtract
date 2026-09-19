"""Fast provisional findings from fetched HTML and completed attempts, without model calls."""
from collections import Counter

from bs4 import BeautifulSoup

from abtract.schemas import Episode, JobPreview, PreviewAttempt, Task


def inspect_page(path: str, html: bytes) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    notes = []
    canvases = len(soup.find_all("canvas"))
    if canvases:
        notes.append(f"{path}: {canvases} canvas element(s). Checking whether agents can read information drawn inside them.")
    unlabeled = 0
    for control in soup.find_all(["input", "select", "textarea"]):
        if str(control.get("type", "")).lower() in {"hidden", "submit", "button", "reset", "image"}:
            continue
        labelled_by = [soup.find(id=name) for name in str(control.get("aria-labelledby", "")).split()]
        label = soup.find("label", attrs={"for": control.get("id")}) if control.get("id") else None
        if not (control.get("aria-label") or control.get("title") or control.get("placeholder")
                or any(node and node.get_text(strip=True) for node in labelled_by)
                or (label and label.get_text(strip=True)) or control.find_parent("label")):
            unlabeled += 1
    if unlabeled:
        notes.append(f"{path}: {unlabeled} form field(s) have no label in the fetched HTML. Browser tests will check whether scripts supply one.")
    vague = sum(a.get_text(" ", strip=True).lower() in {"click here", "here", "read more", "learn more"}
                for a in soup.find_all("a"))
    if vague:
        notes.append(f"{path}: {vague} link(s) use generic text such as ‘learn more’. Checking whether agents can identify their destination.")
    return notes


def attempt(ep: Episode, tasks: dict[str, Task]) -> PreviewAttempt:
    if (ep.error or "").startswith("budget exhausted"):
        outcome = "skipped"
    elif ep.failure_mode in {"error", "timeout"} or ep.success is None:
        outcome = "error"
    else:
        outcome = "passed" if ep.success else "failed"
    task = tasks.get(ep.task_id)
    return PreviewAttempt(episode_id=ep.id, task_id=ep.task_id, prompt=task.prompt if task else ep.task_id,
                          model_id=ep.model_id, agent_kind=ep.agent_kind, outcome=outcome,
                          reason=(ep.judge_reason or ep.error or ep.failure_mode or "")[:240])


def update_attempts(preview: JobPreview, results: list[PreviewAttempt]) -> None:
    counts = Counter(result.outcome for result in results)
    preview.completed = len(results)
    preview.passed, preview.failed = counts["passed"], counts["failed"]
    preview.errors, preview.skipped = counts["error"], counts["skipped"]
    preview.recent = list(reversed(results[-6:]))
    groups: dict[str, list[PreviewAttempt]] = {}
    for result in results:
        if result.outcome in {"passed", "failed"}:
            groups.setdefault(result.task_id, []).append(result)
    notes = []
    for group in sorted(groups.values(), key=lambda rows: -sum(r.outcome == "failed" for r in rows)):
        failures = sum(r.outcome == "failed" for r in group)
        if failures:
            notes.append(f"{failures} of {len(group)} completed attempt(s) have failed on ‘{group[0].prompt}’. Other attempts may change this finding.")
        if len(notes) == 3:
            break
    if not notes and preview.passed:
        notes.append(f"All {preview.passed} assessed attempt(s) so far have passed. Remaining attempts are still untested.")
    if preview.errors:
        notes.append(f"{preview.errors} attempt(s) could not be assessed because of execution or timeout errors. These do not establish a website usability issue.")
    if preview.skipped:
        notes.append(f"{preview.skipped} attempt(s) were skipped when the internal allowance was reached.")
    preview.findings = notes
