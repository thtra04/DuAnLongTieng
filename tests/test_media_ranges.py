"""Đường dự phòng tải từng khúc Range khi CDN đóng kết nối giữa chừng (bilibili)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from backend.core import media


class _Resp(io.BytesIO):
    """Giả lập response của urllib: đọc được, có headers, dùng được với `with`."""

    def __init__(self, data: bytes, headers: dict, status: int = 206):
        super().__init__(data)
        self.headers = headers
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class _Server:
    """Máy chủ giả: trả đúng khúc Range được xin, đếm số lượt gọi, có thể lỗi vài lần."""

    def __init__(self, blob: bytes, fail_first: int = 0):
        self.blob = blob
        self.calls = 0
        self.fail_first = fail_first
        self.ranges: list[tuple[int, int]] = []

    def urlopen(self, req, timeout=0):
        self.calls += 1
        if self.calls <= self.fail_first:
            raise ConnectionResetError("máy chủ ngắt")
        rng = req.get_header("Range")
        lo, hi = (int(x) for x in rng.split("=")[1].split("-"))
        hi = min(hi, len(self.blob) - 1)
        self.ranges.append((lo, hi))
        headers = {"Content-Range": f"bytes {lo}-{hi}/{len(self.blob)}"}
        return _Resp(self.blob[lo : hi + 1], headers)


def test_nhan_ra_loi_ngat_ket_noi():
    assert media._looks_truncated(Exception("[download] Got error: 950 bytes read, 10448210 more expected"))
    assert media._looks_truncated(Exception("IncompleteRead(221 bytes read)"))
    assert not media._looks_truncated(Exception("HTTP Error 403: Forbidden"))
    assert not media._looks_truncated(Exception("Unsupported URL"))


def test_content_length_tu_content_range():
    srv = _Server(b"x" * 1234)
    assert media._content_length("http://cdn/a", {}, opener=srv) == 1234
    assert srv.ranges == [(0, 0)]


def test_tai_tung_khuc_ghep_dung_du_lieu(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "_RANGE_CHUNK", 1000)
    blob = bytes(range(256)) * 10  # 2560 byte -> 3 khúc: 1000 + 1000 + 560
    srv = _Server(blob)
    dest = tmp_path / "v.part"
    got: list[int] = []

    media._fetch_ranges("http://cdn/a", {"Referer": "https://www.bilibili.com/"}, dest, len(blob), got.append, opener=srv)

    assert dest.read_bytes() == blob
    assert srv.ranges == [(0, 999), (1000, 1999), (2000, 2559)]
    assert sum(got) == len(blob)


def test_tai_tiep_phan_da_co(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "_RANGE_CHUNK", 1000)
    blob = b"abcdefghij" * 250  # 2500 byte
    dest = tmp_path / "v.part"
    dest.write_bytes(blob[:1500])  # lần trước tải dở
    srv = _Server(blob)

    media._fetch_ranges("http://cdn/a", {}, dest, len(blob), opener=srv)

    assert dest.read_bytes() == blob
    assert srv.ranges == [(1500, 2499)]


def test_thu_lai_khi_khuc_bi_ngat(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "_RANGE_CHUNK", 1000)
    monkeypatch.setattr(media.time if hasattr(media, "time") else __import__("time"), "sleep", lambda s: None)
    blob = b"z" * 1500
    srv = _Server(blob, fail_first=2)
    dest = tmp_path / "v.part"

    media._fetch_ranges("http://cdn/a", {}, dest, len(blob), opener=srv)

    assert dest.read_bytes() == blob
    assert srv.calls == 4  # 2 lượt lỗi + 2 khúc


def test_bo_cuoc_sau_nhieu_lan_ngat(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "_RANGE_CHUNK", 1000)
    monkeypatch.setattr(__import__("time"), "sleep", lambda s: None)
    srv = _Server(b"z" * 100, fail_first=99)

    with pytest.raises(media.MediaError, match="Tải từng khúc thất bại"):
        media._fetch_ranges("http://cdn/a", {}, tmp_path / "v.part", 100, opener=srv, retries=3)


def test_chon_phan_trong_playlist():
    assert media._pick_entry({"title": "a"}, None) == {"title": "a"}
    assert media._pick_entry({"entries": [None, {"title": "p2"}]}, 2) == {"title": "p2"}
    with pytest.raises(media.MediaError, match="phần 3"):
        media._pick_entry({"entries": [None]}, 3)


class _FakeYDL:
    """yt-dlp giả: chỉ có extract_info(download=False) và prepare_filename."""

    def __init__(self, info: dict, outdir: Path):
        self.info = info
        self.outdir = outdir

    def extract_info(self, url, download=False):
        assert download is False
        return self.info

    def prepare_filename(self, info):
        return str(self.outdir / f"{info['title']}.mp4")


def test_download_in_ranges_mot_stream(tmp_path, monkeypatch):
    """Một stream duy nhất: tải xong đổi tên, không cần ffmpeg."""
    import urllib.request

    blob = b"MP4DATA" * 300
    srv = _Server(blob)
    monkeypatch.setattr(urllib.request, "urlopen", srv.urlopen)
    info = {"title": "video", "url": "http://cdn/one", "ext": "mp4", "format_id": "30080",
            "http_headers": {"Referer": "https://www.bilibili.com/"}}
    logs: list[str] = []
    progress: list[float] = []

    out = media._download_in_ranges(_FakeYDL(info, tmp_path), "http://x", None, progress.append, logs.append)

    assert out == tmp_path / "video.mp4"
    assert out.read_bytes() == blob
    assert progress[-1] == 1.0
    assert not list(tmp_path.glob("*.part"))
    assert any("Đã tải" in m for m in logs)


def test_download_in_ranges_ghep_hai_stream(tmp_path, monkeypatch):
    """Video + audio riêng: tải cả hai rồi gọi ffmpeg ghép (ffmpeg giả)."""
    import urllib.request

    srv = _Server(b"S" * 500)
    monkeypatch.setattr(urllib.request, "urlopen", srv.urlopen)
    called: list[list[str]] = []

    def fake_run(cmd, cwd=None):
        called.append(cmd)
        Path(cmd[-1]).write_bytes(b"MUXED")
        return ""

    monkeypatch.setattr(media, "run", fake_run)
    monkeypatch.setattr(media, "ffmpeg_exe", lambda: "ffmpeg")
    info = {
        "title": "video", "ext": "mp4",
        "requested_formats": [
            {"url": "http://cdn/v", "ext": "mp4", "format_id": "30080", "filesize": 500, "http_headers": {}},
            {"url": "http://cdn/a", "ext": "m4a", "format_id": "30280", "filesize": 500, "http_headers": {}},
        ],
    }

    out = media._download_in_ranges(_FakeYDL(info, tmp_path), "http://x", None, None, None)

    assert out.read_bytes() == b"MUXED"
    assert len(called) == 1 and called[0][0] == "ffmpeg" and "-c" in called[0]
    assert not list(tmp_path.glob("*.part"))  # file tạm đã dọn


def test_stream_thay_the_cung_loai_xep_h264_truoc():
    info = {"formats": [
        {"format_id": "av1", "url": "u1", "vcodec": "av01", "acodec": "none", "height": 1080},
        {"format_id": "h264", "url": "u2", "vcodec": "avc1.64", "acodec": "none", "height": 1080},
        {"format_id": "hevc720", "url": "u3", "vcodec": "hvc1", "acodec": "none", "height": 720},
        {"format_id": "4k", "url": "u4", "vcodec": "avc1", "acodec": "none", "height": 2160},
        {"format_id": "aud", "url": "u5", "vcodec": "none", "acodec": "mp4a", "abr": 128},
        {"format_id": "aud2", "url": "u6", "vcodec": "none", "acodec": "mp4a", "abr": 192},
    ]}
    video = info["formats"][0]
    assert [g["format_id"] for g in media._alternatives(info, video)] == ["h264", "hevc720"]
    audio = info["formats"][4]
    assert [g["format_id"] for g in media._alternatives(info, audio)] == ["aud2"]
    assert media._alternatives({}, video) == []


def test_download_in_ranges_doi_sang_stream_khac_khi_cdn_hong(tmp_path, monkeypatch):
    """Stream AV1 đứt cố định ở một byte -> tự chuyển sang stream H.264."""
    import urllib.request

    good = b"H264" * 200
    srv = _Server(good)
    real_urlopen = srv.urlopen

    def urlopen(req, timeout=0):
        if req.full_url == "http://cdn/av1":
            raise ConnectionResetError("CDN hỏng")
        return real_urlopen(req, timeout)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(__import__("time"), "sleep", lambda s: None)
    monkeypatch.setattr(media, "run", lambda cmd, cwd=None: Path(cmd[-1]).write_bytes(b"MUXED"))
    monkeypatch.setattr(media, "ffmpeg_exe", lambda: "ffmpeg")
    av1 = {"format_id": "100026", "url": "http://cdn/av1", "ext": "mp4", "vcodec": "av01", "acodec": "none", "height": 1080, "filesize": 800, "http_headers": {}}
    h264 = {"format_id": "30080", "url": "http://cdn/h264", "ext": "mp4", "vcodec": "avc1", "acodec": "none", "height": 1080, "filesize": 800, "http_headers": {}}
    aud = {"format_id": "30280", "url": "http://cdn/aud", "ext": "m4a", "vcodec": "none", "acodec": "mp4a", "filesize": 800, "http_headers": {}}
    info = {"title": "video", "ext": "mp4", "requested_formats": [av1, aud], "formats": [av1, h264, aud]}
    logs: list[str] = []

    out = media._download_in_ranges(_FakeYDL(info, tmp_path), "http://x", None, None, logs.append)

    assert out.read_bytes() == b"MUXED"
    assert any("stream thay thế" in m for m in logs)
    assert any("hỏng trên CDN" in m for m in logs)
    assert not list(tmp_path.glob("*.part"))


def test_download_in_ranges_moi_stream_deu_hong_thi_bao_loi(tmp_path, monkeypatch):
    import urllib.request

    def urlopen(req, timeout=0):
        raise ConnectionResetError("CDN hỏng")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(__import__("time"), "sleep", lambda s: None)
    only = {"format_id": "1", "url": "http://cdn/1", "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a", "filesize": 10, "http_headers": {}}
    info = {"title": "video", "ext": "mp4", "url": "http://cdn/1", "format_id": "1", "vcodec": "avc1", "acodec": "mp4a", "filesize": 10, "formats": [only]}

    with pytest.raises(media.MediaError, match="Không tải được stream nào"):
        media._download_in_ranges(_FakeYDL(info, tmp_path), "http://x", None, None, None)
