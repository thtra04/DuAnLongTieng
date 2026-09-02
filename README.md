# 🎬 VSub Studio

Tool tạo **phụ đề** và **dịch video** chạy hoàn toàn trên máy bạn, giao diện web tiếng Việt.

- 🎙️ **Tự nghe lời thoại** trong video bằng Whisper (99 ngôn ngữ), có mốc giờ tới từng từ
- 📄 **Canh theo văn bản của bạn** — dán sẵn kịch bản, tool nghe video rồi khớp giờ từng câu
- 🗂️ **Nạp file .srt/.vtt có sẵn** để dịch và chỉnh sửa
- 🔗 **Tải từ link** YouTube / TikTok / Facebook / bilibili — link nhiều phần sẽ được hỏi chọn phần
- 🌐 **Dịch giữa 41 ngôn ngữ** — Google (miễn phí), NLLB-200 (offline), Claude / OpenAI (chất lượng cao)
- 🎙️ **Lồng tiếng Việt** — 14 giọng Bắc/Trung/Nam, hoặc nhân bản chính giọng người nói trong video
- 🎨 **Biên tập trực quan** — xem trước phụ đề chồng lên video, sửa từng dòng, đổi font/màu/vị trí
- 📦 **Xuất** SRT · VTT · SRT song ngữ · TXT · video nung phụ đề · video phụ đề bật-tắt · video lồng tiếng
- 📂 **Dự án phim** — tạo bộ → tạo tập → đưa video vào từng tập; theo dõi còn thiếu tập nào

---

## Cài đặt

Cần [uv](https://docs.astral.sh/uv/) (quản lý Python & thư viện):

```bash
uv sync --extra cuda
```

Cài thêm engine dịch (tuỳ chọn):

```bash
uv sync --extra cuda --extra ai        # + Claude / OpenAI API
uv sync --extra cuda --extra offline   # + NLLB-200 dịch offline (tải torch ~2.5 GB)
uv sync --extra cuda --extra tts       # + lồng tiếng Việt VieNeu-TTS (14 giọng có sẵn)
uv sync --extra cuda --extra clone     # + nhân bản giọng trong video (kéo torch ~2.5 GB)
```

Cài tất cả:

```bash
uv sync --extra cuda --extra ai --extra offline --extra tts --extra clone
```

`ffmpeg` đã đi kèm sẵn qua gói `imageio-ffmpeg` — không cần cài gì thêm.
Nếu muốn bản đầy đủ (kèm `ffprobe`):

```bash
uv run python -m app.setup_ffmpeg
```

## Chạy

```bash
uv run python run.py
```

Trình duyệt tự mở <http://127.0.0.1:8000>.

| Tuỳ chọn | Ý nghĩa |
|---|---|
| `--port 8080` | đổi cổng |
| `--host 0.0.0.0` | cho máy khác trong LAN truy cập |
| `--no-browser` | không tự mở trình duyệt |
| `--reload` | tự nạp lại khi sửa code (dev) |

---

## Dùng thế nào

### 📂 Dự án phim

Thẻ đầu tiên ở bước 1. Làm theo **ba bước, đúng thứ tự đó**:

```
1. tạo bộ phim   →   2. tạo tập   →   3. đưa link / upload video cho tập đó
```

Nghĩa là **một tập tồn tại trước khi có video**. Bộ phim do bạn tạo, tool không đoán từ link —
đó là lý do video upload từ máy cũng gom vào bộ được (trước đây không link thì không gộp nổi).

**Bước 1 — tạo bộ.** Bấm `➕ Tạo dự án phim`, đặt tên. Dán thêm **link cả bộ** thì tool đọc link,
**tạo sẵn từng tập** kèm tên và thời lượng, và **tự nhận những tập bạn đã làm trước đó** vào đúng chỗ.

**Bước 2 — tạo tập.** `➕ Thêm tập` trong thẻ bộ (link nhiều phần thì đã có sẵn, bỏ qua bước này).

**Bước 3 — đưa video vào.** Bấm `📥 Đưa video vào` ở tập cần làm. Về bước 1 với **băng xanh
"🎯 Đang làm tập 2 của bộ …"**, bộ có link thì tự dán link và chọn đúng phần. Xong phân tích là
kết quả **tự gắn vào đúng tập**.

```
🎬 Đại Hán Thiên Mệnh Nhân       ➕ Thêm tập  ✏️ Đổi tên  🗑 Xoá bộ  ▾
   Đã làm 3 trong 5 tập  ▓▓▓▓▓▓░░░░
   ── ĐÃ LÀM — 3 TẬP ──────────────────────────────────────────
   ┌───┐  P-1 · Tiếng Việt → Tiếng Anh · 259 dòng · 48 phút
   │ 1 │  Đã xuất: SRT VTT TXT       [Mở ra sửa]  [🗑 Xoá tập]
   │TẬP│
   └───┘
   ── CHƯA CÓ VIDEO — 2 TẬP ───────────────────────────────────
   ┌───┐  P-2 · 7 giờ 21 phút
   │ 2 │  Chưa có video — cần dán link hoặc upload
   │TẬP│                        [📥 Đưa video vào]  [🗑]
   └───┘
```

| Chỗ bấm | Làm gì |
|---|---|
| **📥 Đưa video vào** | Bước 3 của luồng — về bước 1 để chọn nguồn cho đúng tập đó |
| **Mở ra sửa** | Vào bước 4 với phụ đề cũ — sửa rồi xuất thêm định dạng, **không phải nghe & dịch lại** |
| **SRT VTT TXT** (nhãn xanh) | Tải lại file đã xuất trước đó |
| **🗑 Xoá tập** | Mất phụ đề của tập đó; tập quay về *chưa có video*. Tập chưa có video thì bỏ khỏi bộ, không mất gì |
| **🗑 Xoá bộ** | Cả bộ, kèm phụ đề mọi tập |

Video làm trước khi tạo bộ nằm ở mục **Chưa thuộc bộ nào** cuối dashboard — bấm **Gán vào bộ**
để đưa vào một tập trống.

Xoá tập/bộ đều mất phụ đề, file đã xuất và bản video tool đang giữ; **video gốc trên máy bạn
không bị đụng**. Video đang được dự án khác dùng chung thì giữ lại.

Bộ phim & tập lưu ở `data/films.json`; phụ đề vẫn ở `data/jobs/<id>/state.json`.

Dự án nào mất video gốc (đã dọn `data/uploads/`) hiện nhãn **video gốc đã mất**: vẫn sửa và
xuất được SRT · VTT · TXT, nhưng không xem trước và không nung / lồng tiếng được.

### Bước 1 — Nguồn video

Kéo thả file (`mp4, mkv, mov, avi, webm, mp3, wav…`) hoặc dán link YouTube/TikTok/Facebook/bilibili.

**Link nhiều phần** — một link bilibili có thể chứa nhiều phần (`P1, P2, P3…`), playlist YouTube
cũng vậy. Bấm **🔍 Kiểm tra link** (hoặc chỉ cần rời khỏi ô nhập) để xem danh sách phần kèm thời
lượng, rồi chọn phần muốn xử lý — mỗi lần một phần. Chưa chọn thì tool không cho đi tiếp, tránh
chuyện tải nhầm một phần dài 9 tiếng.

Rồi chọn phụ đề lấy từ đâu:

| Chế độ | Khi nào dùng |
|---|---|
| 🎙️ **Tự nghe từ video** | Video có tiếng, bạn không có sẵn lời thoại |
| 📄 **Theo văn bản của tôi** | Bạn đã có kịch bản/lời thoại — muốn phụ đề đúng từng chữ mình viết |
| 🗂️ **Đã có .srt/.vtt** | Chỉ cần dịch hoặc chỉnh kiểu chữ rồi nung vào video |

### Bước 2 — Ngôn ngữ & engine dịch

| Engine | Chất lượng | Chi phí | Cần mạng |
|---|---|---|---|
| **Google Translate** | Tốt | Miễn phí | Có |
| **MyMemory** | Khá (dự phòng) | Miễn phí | Có |
| **NLLB-200** | Khá | Miễn phí | Không |
| **Claude API** | Tốt nhất — hiểu ngữ cảnh cả đoạn | Trả phí | Có |
| **OpenAI API** | Rất tốt | Trả phí | Có |

> 💡 Engine AI dịch theo lô ~40 dòng một lần nên hiểu được mạch hội thoại. Ô **"Bối cảnh video"**
> giúp tránh dịch sai thuật ngữ — ví dụ Google dịch "Whisper" thành "lời thì thầm", còn AI biết
> đó là tên model nếu bạn ghi rõ bối cảnh.

**Bản dịch không bị lệch dòng.** Cả 5 engine đều gán bản dịch vào **đúng cue** kể cả khi trả về
thiếu hoặc đảo thứ tự: Google/MyMemory kiểm số đoạn tách được, sai thì dịch lại từng dòng; engine
AI dùng giao thức số dòng (`3 | nội dung`) nên gán theo số model trả về chứ không theo vị trí.
Dòng nào AI bỏ sót thì **giữ nguyên văn gốc** và log cảnh báo rõ bao nhiêu dòng — không im lặng
để phụ đề lẫn chữ nước ngoài.

**Model Whisper**: `tiny` → `large-v3`. `medium` là điểm cân bằng tốt.
Lần đầu dùng model nào sẽ tải model đó về `data/models/`.
Máy có GPU NVIDIA sẽ tự động dùng GPU (nhanh hơn ~5–10 lần); không có thì tự chuyển sang CPU.

#### Lọc khoảng lặng (VAD) — mặc định TẮT

VAD bỏ qua các đoạn không có tiếng nói để chạy nhanh hơn. Nhưng với **video ca nhạc**,
nó thường tưởng phần hát là nhạc rồi cắt bỏ — dẫn tới phụ đề chỉ ra được vài chục giây đầu.

Đo trên một MV 3 phút 36 giây:

| Cấu hình | Số dòng | Độ phủ |
|---|---:|---:|
| VAD bật | 7 | 21% |
| VAD tắt | 32 | **95%** |

Vì vậy VAD mặc định tắt. Chỉ bật khi video là phỏng vấn/thuyết trình có nhiều đoạn im lặng thật.

#### Tự sửa khi phụ đề bị hụt — mặc định BẬT

Whisper có thể bỏ sót cả đoạn dài **mà không báo lỗi**. Tool luôn đo độ phủ và:

1. Nếu phủ dưới 85% và VAD đang bật → tự nhận dạng lại không dùng VAD, giữ kết quả tốt hơn
2. Quét bù các khoảng trống dài trên 20 giây (lọc chặt theo `no_speech_prob` và `avg_logprob`
   để Whisper không bịa lời trên đoạn nhạc/im lặng)
3. Nếu vẫn hụt, hiện cảnh báo rõ ràng ở bước 3 kèm danh sách đoạn thiếu — không bao giờ
   im lặng trả về kết quả cụt

### Bước 3 — Xử lý

Xem tiến độ từng bước và log thời gian thực. Có thể bấm **Huỷ** bất cứ lúc nào.

### Bước 4 — Biên tập & xuất

- Bấm một dòng để tua video tới đúng chỗ đó
- Sửa trực tiếp lời gốc và bản dịch trong ô
- Chỉ số **cps** (ký tự/giây) chuyển vàng khi > 22 — dấu hiệu phụ đề trôi quá nhanh
- Đổi font, cỡ chữ, màu, viền, vị trí — xem trước ngay trên video
- **Lệch giờ** để đẩy toàn bộ phụ đề sớm/muộn nếu bị lệch tiếng

Phím tắt: `Space` phát/dừng · `←` `→` nhảy dòng trước/sau.

### Lồng tiếng (tuỳ chọn)

Bật **Lồng tiếng** ở bước 4 để video nói tiếng Việt thay vì chỉ có phụ đề.

| Tuỳ chọn | Ý nghĩa |
|---|---|
| **Giọng đọc** | 14 giọng dựng sẵn (nam/nữ × Bắc/Trung/Nam × tin tức/tự nhiên/kể chuyện) |
| 🧬 **Nhân bản giọng trong video** | Cắt 4–8 giây có tiếng nói từ chính video rồi bắt chước giọng đó |
| **Phong cách đọc** | Tự nhiên · Bản tin · Đọc truyện |
| **Giữ tiếng gốc ở nền** | Vẫn nghe được nhạc nền và tiếng động; bỏ chọn để thay hẳn tiếng gốc |
| **Tự cân âm lượng** | Chuẩn hoá giọng đọc lên sát mức tối đa, và hạ nền thêm nếu tiếng gốc còn to quá |
| **Tiếng gốc chỉ nhỏ lại khi có người đọc** | Ducking: đoạn không ai đọc vẫn nghe nguyên nhạc/tiếng động |
| **Âm lượng giọng đọc** | Nhân thêm lên mức tool đã tự cân (mặc định 100%). Kéo lên nếu vẫn thấy lép |
| **Âm lượng tiếng gốc** | **Mức tối đa** của tiếng gốc — mặc định 45%. Tool chỉ được hạ xuống, không tự nâng lên |
| **Tăng tốc tối đa** | Câu dịch dài hơn khung giờ sẽ được đọc nhanh hơn (giữ nguyên cao độ) tới mức này |

Bấm **🔊 Nghe thử giọng** để nghe ngay dòng đang chọn trước khi xuất.

**Đọc theo câu trọn, không đọc từng dòng phụ đề.** Đây là chỗ quyết định chất lượng.

Phụ đề bị cắt theo **giới hạn ký tự**, không theo ngữ pháp — Whisper tiếng Trung gần như không
trả dấu câu (đo trên một video thật: 18 dấu / 1768 ký tự, 53/69 cue bị cắt vì đủ 28 ký tự, chỉ
8/69 kết ở dấu câu). Sau đó bước dịch gom cue thành câu để dịch trọn ý rồi **chia lại bản dịch
theo tỉ lệ số ký tự**, nên 68/69 cue nhận một mảnh cụt: 48 mảnh không kết bằng dấu câu, **41 chỗ
một từ bị chẻ đôi**.

Đọc từng mảnh đó thì TTS xuống giọng và nghỉ ngay giữa từ. Vì vậy tool **nối các mảnh của cùng
một câu lại rồi đọc trọn một lần** trong đúng khoảng thời gian của cả nhóm. Đo trên video thật
(69 cue / 392 s):

| | Đọc từng dòng | Đọc câu trọn |
|---|---:|---:|
| Số lần đọc | 69 | 24 |
| Câu phải tăng tốc | 48 | **13** |
| Nén mạnh nhất | 1,48× | **1,23×** |
| Tràn khung | 2 chỗ | **1 chỗ (0,4 s)** |
| Lệch nội dung p75 | 518 ms | **468 ms** |
| p90 | 780 ms | **747 ms** |

Giọng bị nén nghe gấp và máy móc là khuyết điểm dễ nghe nhất, nên đọc câu trọn ăn ở chỗ đó:
**48 → 13 câu** phải tăng tốc.

**Canh mốc giờ.** Mỗi đơn vị đọc được đặt vào mốc bắt đầu của cue đầu tiên trong nhóm — mốc
tuyệt đối, nên **sai số không dồn về sau**. Đọc dài hơn khung thì lấn sang khoảng lặng phía sau,
vẫn không đủ thì tăng tốc bằng `atempo` (không đổi cao độ) tới `Tăng tốc tối đa`. Vẫn tràn thì
log chỉ đúng nhóm dòng nào để bạn rút gọn.

**Cân âm lượng.** Giọng VieNeu-TTS ra khoảng −18…−20 dBFS, còn thoại gốc trong phim thường
−10…−13 dBFS — để nguyên là giọng lồng vào nghe lép hơn thoại gốc. Tool đo mức *phần có tiếng*
của track lồng tiếng (bỏ khoảng lặng, vì track im tới 80–90% thời lượng nên RMS cả file lệch cả
chục dB), đo tiếng gốc bằng mẫu 2 phút giữa phim, rồi chuẩn hoá giọng về **−16 dBFS**.

Đỉnh **không** dùng để chặn mức kéo — `build_dub_track` ghim đỉnh track về 0.99 khi các dòng
chồng nhau, nên lấy đỉnh làm trần thì mức kéo luôn ra 0 dB và giọng vĩnh viễn ở mức thô. Việc
chống vỡ tiếng do `alimiter` ở cuối chuỗi trộn lo (trần 0.89, chừa chỗ cho aac vọt ~1 dB).

**Ducking.** Tiếng gốc đứng ở mức bạn đặt khi không ai đọc, rồi hụp thêm **5 dB** lúc người đọc
đang nói. Cố ý hụp ít: chênh lệch lớn giữa hai mức làm nền gào lên mỗi lần người đọc ngưng rồi
tụt xuống khi đọc lại — đó mới là cái nghe khó chịu nhất, khó chịu hơn cả việc giọng hơi nhỏ.

> Nếu bạn chọn cả **Video nung phụ đề**, tiếng sẽ được lồng lên chính bản đó — ra một
> video vừa có chữ vừa có tiếng Việt.

| Định dạng xuất | Ghi chú |
|---|---|
| `.srt` | Phổ biến nhất, mở được ở mọi nơi |
| `.vtt` | Dùng cho web / HTML5 |
| `.srt` song ngữ | Gốc + dịch trên 2 dòng |
| `.txt` | Toàn bộ lời thoại, không mốc giờ |
| **Video nung phụ đề** | Chữ dính vào hình, xem ở đâu cũng có sub — phải encode lại nên lâu nhất |
| **Video phụ đề bật/tắt** | Gắn dạng track, gần như tức thì, người xem tự bật/tắt |
| **Video lồng tiếng** | Đọc bản dịch thành tiếng Việt và ghép vào video |
| **File tiếng .WAV** | Chỉ riêng track lồng tiếng, để bạn tự dựng |

---

## Cấu trúc

```
app/
  main.py         API FastAPI + phục vụ giao diện
  pipeline.py     Điều phối: nguồn → phụ đề → dịch → xuất
  asr.py          Whisper (faster-whisper), tự chọn GPU/CPU
  align.py        Canh văn bản người dùng vào timeline lời nói
  translate.py    5 engine dịch
  subtitles.py    Đọc/ghi SRT, VTT, ASS; cắt dòng từ word-timestamps
  dubbing.py      Lồng tiếng VieNeu-TTS: đọc, ép vừa khung giờ, trộn tiếng
  media.py        ffmpeg, ffprobe, yt-dlp (kèm đọc link nhiều phần)
  films.py        Kho bộ phim & tập (data/films.json)
  projects.py     Đọc lại phụ đề cũ từ data/jobs/*/state.json, dựng dashboard
  series.py       Suy mã bộ từ link — chỉ dùng lúc tạo bộ để nhận tập đã làm sẵn
  hf_cache.py     Sửa cache HuggingFace bị mất symlink
  jobs.py         Job chạy nền + tiến độ
  languages.py    41 ngôn ngữ (mã Whisper / Google / NLLB)
web/              Giao diện (HTML/CSS/JS thuần, không cần build)
data/             Video upload, kết quả job, model đã tải  (không commit)
```

## Biến môi trường

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Key Claude (khỏi nhập trên giao diện) |
| `OPENAI_API_KEY` | — | Key OpenAI |
| `VSUB_DATA_DIR` | `./data` | Nơi lưu upload & kết quả |
| `VSUB_MODEL_DIR` | `./data/models` | Nơi lưu model đã tải |
| `VSUB_ASR_MODEL` | `medium` | Model Whisper mặc định |
| `VSUB_MAX_UPLOAD` | `4294967296` | Giới hạn upload (bytes) |

---

## Xử lý sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| Pill "không nung được" | `uv run python -m app.setup_ffmpeg` |
| ASR chạy CPU dù có GPU | `uv sync --extra cuda` — cần driver NVIDIA hỗ trợ CUDA 12 |
| Hết VRAM khi dùng `large-v3` | Chọn model nhỏ hơn, hoặc đặt Thiết bị = CPU |
| Google Translate lỗi/bị chặn | Chuyển sang MyMemory hoặc NLLB-200 |
| Phụ đề lệch tiếng | Chỉnh **Lệch giờ** ở bước 4 |
| Video không có tiếng | Dùng chế độ "Đã có .srt/.vtt" |
| **Video dài nhưng chỉ ra phụ đề vài chục giây đầu** | Tắt **Lọc khoảng lặng (VAD)** và bật **Tự sửa khi phụ đề bị hụt** (cả hai đã là mặc định). Nếu vẫn hụt: chọn model `medium`/`large-v3` và chọn đúng ngôn ngữ gốc thay vì để tự động |
| Xử lý nhầm nguồn (file vs link) | Ở bước 1 có dòng xanh ghi rõ **"Sẽ xử lý…"** — tải file lên sẽ tự chuyển sang tab file |
| Link bilibili/playlist có nhiều phần | Bước 1 bấm **🔍 Kiểm tra link** → chọn phần trong danh sách (có kèm thời lượng). Mỗi lần chạy một phần |
| "Phiên làm việc đã hết hạn" khi xuất file | Phụ đề đã sửa vẫn còn trong trang. Chọn lại đúng file video ở bước 1 rồi bấm Xuất file — không phải nhận dạng lại |
| Lồng tiếng bị tắt trong giao diện | `uv sync --extra tts` rồi khởi động lại tool |
| Nhân bản giọng báo thiếu `torch` | `uv sync --extra clone`. Giọng có sẵn không cần torch — chỉ tính năng nhân bản mới cần |
| Phụ đề xem trước lệch với tiếng | Ô **Lệch giờ** ở bước 4 — sửa là thấy đổi ngay. Số dương = chữ hiện muộn hơn |
| Lần đầu mở danh sách giọng rất lâu | Bình thường — đang tải model TTS (~1 phút), lần sau sẽ nhanh |
| Tiếng lồng bị tràn sang câu sau | Rút gọn câu dịch, hoặc kéo **Tăng tốc tối đa** lên 1.7–2.0× |

Model đã tải nằm trong `data/models/` (Whisper, NLLB) và cache mặc định của Hugging Face (VieNeu-TTS).

---

Chỉ xử lý video bạn có quyền sử dụng. Toàn bộ xử lý chạy trên máy bạn — video không rời khỏi máy,
trừ phần văn bản gửi đi khi dùng engine dịch online (Google / MyMemory / Claude / OpenAI).
