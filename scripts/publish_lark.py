#!/usr/bin/env python3
"""Publish a Video2Doc transcript (ideally an illustrated one) to a Lark/Feishu document.

Requires the official `lark-cli` (https://github.com/larksuite/cli), already
configured and logged in (`lark-cli auth login --domain docs --domain drive`).

Examples:
  python scripts/publish_lark.py --job output/<id> --new "讲座逐字稿"
  python scripts/publish_lark.py --job output/<id> --doc https://xxx.larksuite.com/docx/TOKEN
  python scripts/publish_lark.py --job output/<id> --doc TOKEN --after-block <block_id>

Each slide image is uploaded with its time range as caption, followed by the
narration spoken while it was on screen. `--after-block` moves the whole
section under an existing heading/paragraph (images can only be appended at
the end of a document, so the section is built there first). Progress is
checkpointed in the job folder, so an interrupted run resumes where it stopped.
"""
import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ENV = {**os.environ, "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1", "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1"}
MOVE_BATCH = 40


class LarkError(RuntimeError):
    pass


def doc_token(value):
    match = re.search(r"/(?:docx|wiki)/([A-Za-z0-9]+)", value)
    return match.group(1) if match else value.strip()


def parse_cli_json(text):
    """lark-cli may print progress lines before the JSON envelope."""
    text = text or ""
    start = 0 if text.lstrip().startswith("{") else text.find("\n{") + 1
    try:
        return json.loads(text[start:]) if text.strip() else {}
    except json.JSONDecodeError:
        return {"ok": False, "raw": text[-500:]}


class Lark:
    def __init__(self, executable, cwd):
        self.executable, self.cwd = executable, cwd

    def run(self, args, stdin=None, retries=4):
        last = None
        for attempt in range(retries):
            result = subprocess.run([self.executable, *args, "--as", "user"], input=stdin,
                                    capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", env=ENV, cwd=self.cwd, timeout=300)
            payload = parse_cli_json(result.stdout) if result.stdout.strip() else parse_cli_json(result.stderr)
            if result.returncode == 0 and payload.get("ok", True):
                return payload
            last = payload
            if (payload.get("error") or {}).get("type") in {"authentication", "authorization", "confirmation"}:
                break  # Retrying cannot fix missing login/scope or a required confirmation.
            time.sleep(2 * (attempt + 1))
        raise LarkError(json.dumps(last, ensure_ascii=False)[:600])


def esc(text):
    return html.escape(str(text), quote=False)


def top_level_ids(xml):
    """Ids of top-level blocks; id-less wrappers (<ul>/<ol>, inline tags) are transparent."""
    ids, stack = [], []
    for match in re.finditer(r"<(/?)([a-zA-Z0-9_-]+)([^>]*?)(/?)>", xml):
        closing, tag, attrs, self_closing = match.groups()
        if closing:
            if stack:
                stack.pop()
            continue
        found = re.search(r'\sid="([^"]+)"', attrs)
        if found and not any(stack):
            ids.append(found.group(1))
        if not self_closing and tag not in {"br", "img", "hr"}:
            stack.append(bool(found))
    return ids


def load_job(job_dir):
    job_dir = Path(job_dir)
    meta = json.loads((job_dir / "job.json").read_text(encoding="utf-8")) if (job_dir / "job.json").is_file() else {}
    sections_file = job_dir / "slides" / "sections.json"
    if sections_file.is_file():
        sections = json.loads(sections_file.read_text(encoding="utf-8"))
        for section in sections:
            section["image"] = str(job_dir / "slides" / section["file"])
    else:
        transcript = json.loads((job_dir / "raw" / "tele_result.json").read_text(encoding="utf-8"))
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from webui.pipeline import transcript_paragraphs
        sections = [{"image": None, "time": "", "paragraphs": transcript_paragraphs(transcript)}]
    return meta, sections


def section_header(meta, heading):
    facts = []
    if meta.get("url"):
        facts.append(f'原视频：<a href="{esc(meta["url"])}">{esc(meta["url"])}</a>')
    if meta.get("duration"):
        facts.append(f"时长 {esc(meta['duration'])}")
    xml = f"<h3>{esc(heading)}</h3>"
    if facts:
        xml += f"<p>{'　'.join(facts)}</p>"
    return xml + ("<p>每张图是视频画面截图，图下标注它出现的时间段，紧跟这段时间里讲者的原话。"
                  "文字由 Video2Doc 自动转写，人名与术语请以原视频为准。</p>")


def publish(lark, job_dir, doc, *, heading, after_block=None, attach=True):
    job_dir = Path(job_dir)
    meta, sections = load_job(job_dir)
    state_file = job_dir / f"lark_publish_{doc}.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.is_file() else {"next": -1}

    def save():
        state_file.write_text(json.dumps(state), encoding="utf-8")

    def append(xml):
        lark.run(["docs", "+update", "--doc", doc, "--command", "append", "--content", "-"], stdin=xml)

    if state["next"] < 0:
        append(section_header(meta, heading))
        state["next"] = 0
        save()
    for index in range(state["next"], len(sections)):
        section = sections[index]
        if section.get("image") and not state.get(f"img{index}"):
            lark.run(["docs", "+media-insert", "--doc", doc, "--file", os.path.relpath(section["image"], lark.cwd),
                      "--width", "720", "--align", "center", "--caption", section["time"]])
            state[f"img{index}"] = True
            save()
        if section["paragraphs"]:
            append("".join(f"<p>{esc(p)}</p>" for p in section["paragraphs"]))
        state["next"] = index + 1
        save()
        print(f"  {index + 1}/{len(sections)}", file=sys.stderr, flush=True)
    if attach and not state.get("attached"):
        for name in ("transcript.md", "transcript.txt", "transcript.srt"):
            if (job_dir / name).is_file():
                lark.run(["docs", "+media-insert", "--doc", doc, "--type", "file",
                          "--file", os.path.relpath(job_dir / name, lark.cwd)])
        state["attached"] = True
        save()
    if after_block and not state.get("moved"):
        moved = move_section(lark, doc, heading, after_block)
        state["moved"] = True
        save()
        print(f"  moved {moved} blocks after {after_block}", file=sys.stderr)


def move_section(lark, doc, heading, after_block):
    """Move the most recently appended `heading` section (to document end) after `after_block`."""
    outline = lark.run(["docs", "+fetch", "--doc", doc, "--scope", "outline", "--max-depth", "6"])
    content = outline["data"]["document"]["content"]
    starts = re.findall(r'<h[1-6] id="([^"]+)"[^>]*>' + re.escape(esc(heading)) + r"</h[1-6]>", content)
    if not starts:
        raise LarkError("刚追加的章节标题未找到，无法移动")
    chunk = lark.run(["docs", "+fetch", "--doc", doc, "--scope", "range", "--start-block-id", starts[-1],
                      "--end-block-id", "-1", "--detail", "with-ids", "--max-depth", "0"])
    body = re.sub(r"^<fragment[^>]*>|</fragment>$", "", chunk["data"]["document"]["content"].strip())
    ids, anchor = top_level_ids(body), after_block
    for index in range(0, len(ids), MOVE_BATCH):
        batch = ids[index:index + MOVE_BATCH]
        lark.run(["docs", "+update", "--doc", doc, "--command", "block_move_after",
                  "--block-id", anchor, "--src-block-ids", ",".join(batch)])
        anchor = batch[-1]
    return len(ids)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="把 Video2Doc 文稿（推荐图文稿）发布到飞书 / Lark 文档")
    parser.add_argument("--job", required=True, help="Video2Doc 任务目录（output/<任务 ID>）")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--doc", help="已有文档 URL 或 token（内容追加到末尾）")
    target.add_argument("--new", metavar="TITLE", help="新建文档并写入")
    parser.add_argument("--after-block", help="写完后把整节移动到该 block 之后")
    parser.add_argument("--heading", default="逐字稿（图文版）", help="章节标题")
    parser.add_argument("--no-attach", action="store_true", help="不附加 transcript.md/txt/srt 文件")
    args = parser.parse_args(argv)

    executable = shutil.which("lark-cli")
    if not executable:
        parser.error("未找到 lark-cli：请先安装并登录（npm i -g @larksuite/cli，然后 lark-cli auth login）")
    job_dir = Path(args.job).resolve()
    if not job_dir.is_dir():
        parser.error(f"任务目录不存在：{job_dir}")
    lark = Lark(executable, cwd=str(job_dir))  # lark-cli only accepts paths relative to cwd
    try:
        if args.new:
            created = lark.run(["docs", "+create", "--content", "-"], stdin=f"<title>{esc(args.new)}</title>")
            doc = created["data"]["document"]["document_id"]
        else:
            doc = doc_token(args.doc)
        publish(lark, job_dir, doc, heading=args.heading, after_block=args.after_block,
                attach=not args.no_attach)
    except LarkError as exc:
        print(f"❌ 发布失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "document_id": doc}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
