"""Gom các dự án cùng một bộ phim.

Một link bilibili nhiều phần (hay playlist YouTube) sinh ra nhiều dự án riêng —
mỗi tập một `data/jobs/<id>/`. Module này suy ra "mã bộ" từ link để gom chúng
lại, và giữ một file ghi đè nhỏ `data/series.json` cho những gì suy ra không
được (đặt lại tên bộ, video upload không có link nào để mà suy).

Mã bộ cố ý dựa vào phần bất biến của link:
    bilibili   -> mã BV, vì mọi tập chỉ khác nhau ở `?p=`
    YouTube    -> mã playlist nếu có, không thì mã video
    còn lại    -> link đã bỏ fragment và các tham số chỉ-số-tập / theo-dõi
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..config import DATA_DIR

INDEX_PATH = DATA_DIR / "series.json"

STANDALONE = ""  # mã của nhóm "video lẻ" (không suy ra được bộ nào)

_BVID_RE = re.compile(r"/video/(BV[0-9A-Za-z]+)", re.I)
_YT_LIST_RE = re.compile(r"[?&]list=([\w-]+)")
_YT_VIDEO_RE = re.compile(r"(?:youtu\.be/|[?&]v=)([\w-]+)")

# Tham số chỉ đánh số tập hoặc dùng để theo dõi — bỏ đi thì các tập cùng bộ mới
# gom về một mã. Cố tình giữ mọi tham số khác để không gom lẫn hai phim khác nhau.
_DROP_PARAMS = {
    "p", "spm_id_from", "trackid", "vd_source", "from", "from_spmid",
    "seid", "t", "start", "share_source", "buvid",
}


def key_for(url: str) -> str:
    """Mã bộ suy từ link. Trả về `STANDALONE` nếu không có link."""
    url = (url or "").strip()
    if not url:
        return STANDALONE

    m = _BVID_RE.search(url)
    if m:
        return "bilibili:" + m.group(1)

    m = _YT_LIST_RE.search(url)
    if m:
        return "yt-list:" + m.group(1)
    m = _YT_VIDEO_RE.search(url)
    if m:
        return "yt:" + m.group(1)

    return "url:" + _normalize(url)


def _normalize(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _DROP_PARAMS
    ]
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/"),
            urlencode(query),
            "",
        )
    )


# ------------------------------------------------------- file ghi đè


def _load() -> dict:
    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with INDEX_PATH.open("w", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(data, ensure_ascii=False, indent=1))


def overrides() -> dict[str, dict]:
    """{mã bộ: {name, total}} — những gì người dùng đã sửa tay."""
    raw = _load().get("series")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict] = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            out[str(key)] = value
    return out


def set_name(key: str, name: str) -> str:
    """Đặt lại tên bộ. Tên rỗng nghĩa là bỏ ghi đè, quay về tên tự suy."""
    data = _load()
    table = data.setdefault("series", {})
    if not isinstance(table, dict):
        table = data["series"] = {}
    entry = table.setdefault(key, {})
    if not isinstance(entry, dict):
        entry = table[key] = {}

    name = (name or "").strip()[:160]
    if name:
        entry["name"] = name
    else:
        entry.pop("name", None)
    if not entry:
        table.pop(key, None)
    _save(data)
    return name


def forget(key: str) -> None:
    """Bỏ mọi ghi đè của một bộ (dùng khi xoá cả bộ)."""
    data = _load()
    table = data.get("series")
    if isinstance(table, dict) and table.pop(key, None) is not None:
        _save(data)
