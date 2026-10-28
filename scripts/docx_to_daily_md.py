#!/usr/bin/env python3
"""Convert a day's Xiaohongshu Word dump into one Markdown file."""

from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def load_style_names(styles_root: ET.Element) -> dict[str, str]:
    names: dict[str, str] = {}
    for style in styles_root.findall(f"{W}style"):
        style_id = style.get(f"{W}styleId")
        if not style_id:
            continue
        name_el = style.find(f"{W}name")
        names[style_id] = name_el.get(f"{W}val") if name_el is not None else style_id
    return names


def is_heading1(style_id: str | None, style_names: dict[str, str]) -> bool:
    if not style_id:
        return False
    sid = style_id.lower().replace(" ", "").replace("_", "-")
    name = (style_names.get(style_id) or "").lower().replace(" ", "")
    return "heading1" in sid or name in {"heading1", "title"}


def para_style_id(paragraph: ET.Element) -> str | None:
    p_pr = paragraph.find(f"{W}pPr")
    if p_pr is None:
        return None
    p_style = p_pr.find(f"{W}pStyle")
    if p_style is None:
        return None
    return p_style.get(f"{W}val")


def has_drawing(paragraph: ET.Element) -> bool:
    return any(local(node.tag) in {"drawing", "pict"} for node in paragraph.iter())


def para_text(paragraph: ET.Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        tag = local(node.tag)
        if tag == "t" and node.text:
            parts.append(node.text)
        elif tag == "tab":
            parts.append("\t")
        elif tag == "br":
            parts.append("\n")
    return "".join(parts)


def append_text_blocks(lines: list[str], text: str) -> None:
    chunks = [chunk.strip() for chunk in text.split("\n") if chunk.strip()]
    for chunk in chunks:
        lines.append(chunk)
    if chunks:
        lines.append("")


def knowledge_stem(date_label: str) -> str:
    """Turn 2026-10-28 into knowledge_261028."""
    year, month, day = date_label.split("-")
    if len(year) != 4 or len(month) != 2 or len(day) != 2:
        raise ValueError(f"date must be YYYY-MM-DD, got {date_label}")
    return f"knowledge_{year[2:]}{month}{day}"


def convert(docx_path: Path, out_md: Path, date_label: str, source_name: str) -> int:
    with ZipFile(docx_path) as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
        styles_root = ET.fromstring(archive.read("word/styles.xml"))
        image_names = [name for name in archive.namelist() if name.startswith("word/media/")]
        image_bytes = archive.read(image_names[0]) if image_names else None

    style_names = load_style_names(styles_root)
    asset_rel = None
    if image_bytes:
        asset_dir = out_md.parent / "assets"
        asset_dir.mkdir(parents=True, exist_ok=True)
        asset_name = f"{knowledge_stem(date_label)}-image1.png"
        (asset_dir / asset_name).write_bytes(image_bytes)
        asset_rel = f"assets/{asset_name}"

    body = document.find(f"{W}body")
    lines: list[str] = []
    article_count = 0
    seen_doc_title = False
    image_inserted = False

    for child in list(body):
        if local(child.tag) != "p":
            continue
        style_id = para_style_id(child)
        text = para_text(child)
        stripped = text.strip()

        if is_heading1(style_id, style_names):
            title = stripped.replace("\n", " ")
            if not title:
                continue
            if not seen_doc_title:
                seen_doc_title = True
                lines.extend(
                    [
                        f"# {title}",
                        "",
                        f"- 日期：{date_label}",
                        f"- 来源：桌面 `{source_name}`（作者自有成稿）",
                        "- 归档规则：一天一篇 Markdown，文件名 `knowledge_YYMMDD`，日内多篇贴文用二级标题分隔",
                        "",
                    ]
                )
                continue
            article_count += 1
            if lines and lines[-1] != "":
                lines.append("")
            lines.extend(["---", "", f"## {article_count}. {title}", ""])
            continue

        if has_drawing(child) and asset_rel and not image_inserted:
            if stripped:
                append_text_blocks(lines, text)
            lines.extend([f"![配图]({asset_rel})", ""])
            image_inserted = True
            continue

        if not stripped:
            if lines and lines[-1] != "":
                lines.append("")
            continue

        append_text_blocks(lines, text)

    cleaned: list[str] = []
    blank = 0
    for line in lines:
        if line == "":
            blank += 1
            if blank <= 1:
                cleaned.append(line)
        else:
            blank = 0
            cleaned.append(line)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    cleaned.append("")

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(cleaned), encoding="utf-8")
    return article_count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("docx")
    parser.add_argument(
        "out_dir",
        nargs="?",
        default="knowledge",
        help="Directory for knowledge_YYMMDD.md (default: knowledge)",
    )
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()
    docx_path = Path(args.docx)
    out_md = Path(args.out_dir) / f"{knowledge_stem(args.date)}.md"
    count = convert(docx_path, out_md, args.date, docx_path.name)
    readme = out_md.parent / "README.md"
    readme.write_text(
        (
            "# 商业号知识库\n\n"
            "按天归档作者自有成稿。一天一个 Markdown，文件名 `knowledge_YYMMDD.md`。当天多篇贴文写在同一文件里，用二级标题分隔。\n\n"
            "| 日期 | 文件 | 篇数 |\n"
            "| --- | --- | --- |\n"
            f"| {args.date} | [{out_md.name}](./{out_md.name}) | {count} |\n"
        ),
        encoding="utf-8",
    )
    print(f"wrote {out_md} articles={count}")


if __name__ == "__main__":
    main()
