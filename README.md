# 🎬 VSub Studio

Tool tạo **phụ đề** và **dịch video** chạy hoàn toàn trên máy bạn, giao diện web tiếng Việt.

- 🎙️ **Tự nghe lời thoại** trong video bằng Whisper (99 ngôn ngữ), có mốc giờ tới từng từ
- 📄 **Canh theo văn bản của bạn** — dán sẵn kịch bản, tool nghe video rồi khớp giờ từng câu
- 🗂️ **Nạp file .srt/.vtt có sẵn** để dịch và chỉnh sửa
- 🔗 **Tải từ link** YouTube / TikTok / Facebook / bilibili — link nhiều phần sẽ được hỏi chọn phần
- 🌐 **Dịch giữa 41 ngôn ngữ** — Google (miễn phí), NLLB-200 (offline), Claude / OpenAI (chất lượng cao)
- 🎙️ **Lồng tiếng Việt** — 14 giọng Bắc/Trung/Nam, hoặc nhân bản chính giọng người nói trong video
- 🎭 **Lồng tiếng đa nhân vật** — tự nghe ra trong phim có mấy người nói, mỗi nhân vật một giọng riêng
- 🎨 **Biên tập trực quan** — xem trước phụ đề chồng lên video, sửa từng dòng, đổi font/màu/vị trí
- 📦 **Xuất** SRT · VTT · SRT song ngữ · TXT · video nung phụ đề · video phụ đề bật-tắt · video lồng tiếng
- 📂 **Dự án phim** — tạo bộ → tạo tập → đưa video vào từng tập; theo dõi còn thiếu tập nào

---

## Kiến trúc: frontend và backend tách rời

```
backend/                 API + lõi xử lý (Python, FastAPI)
  main.py                dựng app, ghép router, phục vụ giao diện, CORS
  config.py              đường dẫn, cấu hình, tắt telemetry của thư viện
  api/                   router HTTP theo miền — chỉ nhận và trả JSON
    system  tts  media  jobs  films  projects  deps
  core/                  lõi xử lý, không biết gì về HTTP — gọi được từ CLI, test hay server
    asr  align  diarize  translate  budget  duration  dubbing  media
    pipeline  metrics  subtitles  languages  jobs  hf_cache  setup_ffmpeg
  store/                 lưu trữ JSON: films  projects  series
frontend/                giao diện tĩnh HTML/CSS/JS, không cần build
  index.html  config.js  (config.js: địa chỉ backend, window.VSUB_API_BASE)
  css/style.css
  js/                    core → theme → boot → films → source → setup → ai → progress → editor → dubbing → export → prefs → main
                         (theme.js: 6 bảng màu + màu nhấn tuỳ ý, chọn ở góc phải header, nhớ cho lần sau)
training/                notebook huấn luyện AI (.ipynb): sinh dữ liệu, train, khung đo
tests/                   pytest — chạy được không cần torch / pyannote / vieneu
```

Hai bên chỉ nói chuyện qua HTTP JSON dưới `/api/...`; tài liệu API tự sinh ở
<http://127.0.0.1:8000/api/docs>. Backend phục vụ giao diện cho tiện, nhưng giao diện chạy
độc lập được bằng bất kỳ máy chủ tĩnh nào:

```bash
# cửa sổ 1 — backend, cho phép origin của giao diện (Windows: set VSUB_CORS_ORIGINS=...)
VSUB_CORS_ORIGINS=http://127.0.0.1:5500 uv run python run.py --no-browser

# cửa sổ 2 — giao diện; trước đó sửa frontend/config.js:
#   window.VSUB_API_BASE = 'http://127.0.0.1:8000';
python -m http.server -d frontend 5500
```

Mọi đường dẫn `/api/...` trong giao diện đều đi qua `apiUrl()` / `API_BASE` ở `frontend/js/core.js`
— không có chỗ nào ghép cứng địa chỉ backend.

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
uv sync --extra cuda --extra diarize   # + nhận diện người nói → lồng tiếng đa nhân vật
```

Cài tất cả:

```bash
uv sync --extra cuda --extra ai --extra offline --extra tts --extra clone --extra diarize
```

> **Lưu ý:** `uv sync` làm môi trường khớp *đúng* các `--extra` nêu trong lệnh, nhóm nào
> không nêu sẽ bị gỡ. Vì vậy khi cài thêm một nhóm, hãy ghi lại đủ các nhóm đang dùng
> trong cùng một lệnh (ví dụ đang có `tts` mà muốn thêm `ai` thì chạy
> `uv sync --extra cuda --extra tts --extra ai`).

`ffmpeg` đã đi kèm sẵn qua gói `imageio-ffmpeg` — không cần cài gì thêm.
Nếu muốn bản đầy đủ (kèm `ffprobe`):

```bash
uv run python -m backend.core.setup_ffmpeg
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

### 🎭 Lồng tiếng đa nhân vật

Cả phim đọc bằng một giọng thì người xem không phân biệt nổi ai đang nói — đó không phải
chuyện thẩm mỹ mà là điều kiện để hiểu nội dung. Bật **Nhận diện người nói** ở bước 2, tool
nghe đường tiếng của phim rồi gán mỗi dòng phụ đề cho một nhân vật.

```
#12  00:04:21 → 00:04:24   [Vai 1]              18 cps
     朕已经决定了
     Trẫm đã quyết rồi.

#13  00:04:25 → 00:04:27   [Vai 2]              14 cps
     臣遵旨
     Thần tuân chỉ.
```

Sang bước 4, mục **🎭 Giọng cho từng nhân vật** cho bạn đặt tên vai và chọn giọng riêng cho
từng người — hoặc **nhân bản chính giọng nhân vật đó** trong phim.

| Chi tiết | Cách làm |
|---|---|
| **Nhãn nhân vật** | `S1`, `S2`… đánh số theo **tổng thời gian nói giảm dần** — `S1` thường là vai chính, và thứ tự không đổi giữa các lần chạy |
| **Gán dòng cho vai** | Theo **độ chồng lấn thời gian lớn nhất**. Dòng vắt qua hai người thì lấy bên chiếm nhiều hơn |
| **Dòng không rõ ai nói** | Thường là phụ đề trên nền nhạc — đọc bằng giọng ở ô "Giọng đọc" chung |
| **Mẫu nhân bản** | Ưu tiên đoạn thoại **không sát lượt của người khác**, tránh mẫu lai hai giọng |
| **Vai không cắt được mẫu** | Tự chuyển sang giọng dựng sẵn, có báo rõ — không làm hỏng cả bản lồng tiếng |
| **Biết trước số vai** | Điền vào ô **Số nhân vật** ở bước 2 — chính xác hơn hẳn để tool tự đoán |

> Không phụ thuộc ngôn ngữ: bước này chỉ đọc đặc trưng âm học của giọng, nên phim Trung, Hàn,
> Nhật, Anh hay bất kỳ tiếng nào cũng dùng được y như nhau.

**Cần token Hugging Face.** Model `pyannote/speaker-diarization-3.1` yêu cầu chấp nhận điều
khoản: mở trang model, bấm đồng ý, tạo token ở mục *Access Tokens*, rồi dán vào ô ở bước 2
(hoặc đặt biến môi trường `HF_TOKEN` cho khỏi nhập lại).

```bash
uv sync --extra cuda --extra diarize   # nhớ ghi thêm các --extra đang dùng
```

### ⏱ Vừa khung thời gian: dự đoán trước, rút gọn trước, nén sau cùng

Bản dịch tiếng Việt thường dài hơn lời gốc. Cách cũ: dịch xong, lúc lồng tiếng câu nào dài
quá khung thì **nén âm thanh** (`atempo`) — giọng gấp và máy móc. Đo thật trên một clip 392 s:
48/69 câu phải nén, nén tối đa 1,48×.

Cách mới, bật bằng tuỳ chọn **Rút gọn câu vượt khung thời gian** ở bước 2 (`budget_loop`):

```
dịch  →  dự đoán số giây TTS sẽ đọc (mô hình HP-3)  →  so với khung thoại
      →  câu nào vượt: nhắc AI viết lại ngắn hơn, kèm giới hạn âm tiết (tối đa 2 lượt)
      →  vẫn vượt thì mới để atempo lo, và log chỉ rõ dòng nào
```

Chỉ engine Claude / OpenAI rút gọn có kiểm soát được; Google / MyMemory thì vòng lặp chỉ đo và báo.

Phần huấn luyện nằm trong notebook, xem [training/README.md](training/README.md):

| Việc | Notebook |
|---|---|
| Sinh dữ liệu thời lượng đọc bằng VieNeu-TTS (tự động, không gán nhãn tay) | `training/01_sinh_du_lieu_thoi_luong.ipynb` |
| Huấn luyện mô hình dự đoán thời lượng | `training/02_huan_luyen_duration.ipynb` |

```bash
uv run jupyter lab training/
```

Mô hình lưu ở `data/models/duration_vi.json`; chưa có thì tool dùng ước lượng thô ~4,3 âm tiết/giây.
Với `training/data/seed_vi.txt` (86 câu) chỉ là chạy thử đường ống — dữ liệu thật cần vài chục nghìn
câu từ corpus phụ đề, mất khoảng một giây mỗi câu trên CPU.

**Khung đo tự động.** Mỗi lần lồng tiếng, tool ghi `data/jobs/<id>/eval.json`: tỉ lệ câu phải nén,
hệ số nén lớn nhất, tổng thời gian tràn, hệ số thời gian thực, kèm nhãn cấu hình C0…C4 (xem
`backend/core/metrics.py`). Gom và in bảng so sánh:

Mở `training/04_khung_do_ket_qua.ipynb` — nó in bảng Markdown dán thẳng vào báo cáo
và xuất kèm CSV.

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
  diarize.py      Nhận diện người nói (pyannote), gán nhãn nhân vật vào từng dòng
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
| `HF_TOKEN` | — | Token Hugging Face để tải model nhận diện người nói (khỏi nhập trên giao diện) |
| `VSUB_DIARIZE_MODEL` | `pyannote/speaker-diarization-3.1` | Model nhận diện người nói |
| `VSUB_AI_TIMEOUT` | `120` | Giây chờ tối đa cho mỗi lượt gọi API AI (Claude/OpenAI); quá thì thử lại một lần rồi báo lỗi |

---

## Xử lý sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| Pill "không nung được" | `uv run python -m backend.core.setup_ffmpeg` |
| ASR chạy CPU dù có GPU | `uv sync --extra cuda` — cần driver NVIDIA hỗ trợ CUDA 12 |
| Hết VRAM khi dùng `large-v3` | Chọn model nhỏ hơn, hoặc đặt Thiết bị = CPU |
| Google Translate lỗi/bị chặn | Chuyển sang MyMemory hoặc NLLB-200 |
| Phụ đề lệch tiếng | Chỉnh **Lệch giờ** ở bước 4 |
| Video không có tiếng | Dùng chế độ "Đã có .srt/.vtt" |
| **Video dài nhưng chỉ ra phụ đề vài chục giây đầu** | Tắt **Lọc khoảng lặng (VAD)** và bật **Tự sửa khi phụ đề bị hụt** (cả hai đã là mặc định). Nếu vẫn hụt: chọn model `medium`/`large-v3` và chọn đúng ngôn ngữ gốc thay vì để tự động |
| Xử lý nhầm nguồn (file vs link) | Ở bước 1 có dòng xanh ghi rõ **"Sẽ xử lý…"** — tải file lên sẽ tự chuyển sang tab file |
| Link bilibili/playlist có nhiều phần | Bước 1 bấm **🔍 Kiểm tra link** → chọn phần trong danh sách (có kèm thời lượng). Mỗi lần chạy một phần |
| "Phiên làm việc đã hết hạn" khi xuất file | Phụ đề đã sửa vẫn còn trong trang. Chọn lại đúng file video ở bước 1 rồi bấm Xuất file — không phải nhận dạng lại |
| Lồng tiếng bị tắt trong giao diện | Thêm `--extra tts` vào lệnh `uv sync` đang dùng, rồi khởi động lại tool |
| Nhân bản giọng báo thiếu `torch` | Thêm `--extra clone` vào lệnh `uv sync` đang dùng. Giọng có sẵn không cần torch — chỉ tính năng nhân bản mới cần |
| Dịch bằng AI rất lâu hoặc như treo | Bấm **🔌 Kiểm tra kết nối** ở bước 2 để xem endpoint trả lời mất bao lâu và model có tồn tại không. Log job ghi thời gian từng lô; mỗi lượt gọi bị cắt sau `VSUB_AI_TIMEOUT` giây. Bước *Rút gọn câu vượt khung* gọi thêm API, tắt nó nếu endpoint chậm |
| Phụ đề xem trước lệch với tiếng | Ô **Lệch giờ** ở bước 4 — sửa là thấy đổi ngay. Số dương = chữ hiện muộn hơn |
| Lần đầu mở danh sách giọng rất lâu | Bình thường — đang tải model TTS (~1 phút), lần sau sẽ nhanh |
| Tiếng lồng bị tràn sang câu sau | Rút gọn câu dịch, hoặc kéo **Tăng tốc tối đa** lên 1.7–2.0× |

Model đã tải nằm trong `data/models/` (Whisper, NLLB) và cache mặc định của Hugging Face (VieNeu-TTS).

---

## Dữ liệu nào rời khỏi máy — và khi nào

Video và âm thanh của bạn **không bao giờ** rời khỏi máy. Bảng dưới liệt kê *mọi* kết nối ra ngoài
mà tool có thể tạo, theo kết quả rà soát mã nguồn và toàn bộ 190 gói thư viện đang cài (9/2026).

| Khi bạn làm gì | Cái gì được gửi | Gửi tới đâu |
|---|---|---|
| Dán link video | Link đó (và mã BV nếu là bilibili) | Trang video · `api.bilibili.com` để lấy tên phần |
| Dịch bằng **Google** | Chữ phụ đề | `translate.google.com` |
| Dịch bằng **MyMemory** | Chữ phụ đề — **qua HTTP thường, không mã hoá** | `api.mymemory.translated.net` |
| Dịch bằng **Claude / OpenAI** | Chữ phụ đề + ô "Bối cảnh video" + bộ thuật ngữ, kèm API key | Anthropic / OpenAI, hoặc `base_url` bạn tự đặt |
| Tải model lần đầu | Token Hugging Face (nếu có) và phiên bản Python/torch trong User-Agent | `huggingface.co` |
| Cài ffmpeg đầy đủ | Không gì cả, chỉ tải về | `gyan.dev` / `johnvansickle.com` |

Không gửi trong mọi trường hợp: tên file, nội dung video, audio, phụ đề khi dịch offline (NLLB),
và không có thống kê sử dụng nào của riêng tool.

**Telemetry của thư viện — đã tắt sẵn.** `pyannote.audio` (nhận diện người nói) mặc định gửi
thời lượng file audio, số nhân vật và tên model về `otel.pyannote.ai` mỗi lần chạy. Tool đặt
`PYANNOTE_METRICS_ENABLED=false` (cùng `HF_HUB_DISABLE_TELEMETRY`, `GRADIO_ANALYTICS_ENABLED`)
ngay lúc khởi động, trước khi bất kỳ thư viện nào được nạp — xem [backend/config.py](backend/config.py).
Muốn bật lại thì đặt biến môi trường trước khi chạy; tool không ghi đè lựa chọn của bạn.

**Giọng lồng tiếng có dấu ẩn.** VieNeu-TTS đóng một watermark không nghe thấy (thư viện Perth)
vào mọi đoạn tiếng nó sinh ra, để nhận diện được đó là giọng tổng hợp. Watermark này không mang
thông tin về bạn và không gửi gì đi đâu.

Server mặc định chỉ nghe ở `127.0.0.1`. Chạy `--host 0.0.0.0` thì mọi máy trong mạng LAN dùng
được tool mà không cần mật khẩu — chỉ làm vậy trong mạng bạn tin.

Chỉ xử lý video bạn có quyền sử dụng.
