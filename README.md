# 🎬 VSub Studio

Tool tạo **phụ đề** và **dịch video** chạy hoàn toàn trên máy bạn, giao diện web tiếng Việt.

- 🎙️ **Tự nghe lời thoại** trong video bằng Whisper (99 ngôn ngữ), có mốc giờ tới từng từ
- 📄 **Canh theo văn bản của bạn** — dán sẵn kịch bản, tool nghe video rồi khớp giờ từng câu
- 🗂️ **Nạp file .srt/.vtt có sẵn** để dịch và chỉnh sửa
- 🔗 **Tải từ link** YouTube / TikTok / Facebook / bilibili — link nhiều phần sẽ được hỏi chọn phần
- 🌐 **Dịch giữa 41 ngôn ngữ** — Google (miễn phí), NLLB-200 (offline), Claude / OpenAI (chất lượng cao)
- 🎙️ **Lồng tiếng Việt** — 14 giọng Bắc/Trung/Nam, hoặc nhân bản chính giọng người nói trong video
- 🎭 **Lồng tiếng đa nhân vật** — tự nghe ra trong phim có mấy người nói, mỗi nhân vật một giọng riêng
- 👫 **Tách giọng nam / nữ** — nhân vật nam đọc giọng nam, nữ đọc giọng nữ, không cần cài thêm gì
- 🎨 **Biên tập trực quan** — xem trước phụ đề chồng lên video, sửa từng dòng, đổi font/màu/vị trí
- 📦 **Xuất** SRT · VTT · SRT song ngữ · TXT · video nung phụ đề · video phụ đề bật-tắt · video lồng tiếng
- 📂 **Dự án phim** — tạo bộ → tạo tập → đưa video vào từng tập; theo dõi còn thiếu tập nào

**Giao diện:** bấm **Giao diện** ở màn hình đăng nhập hoặc trên thanh đầu của studio
(điện thoại: **Tùy chọn → Giao diện**). Mặc định là **Champagne sáng** với nền ngà và ánh vàng;
**Première** là lựa chọn xanh trầm nếu thích nền tối. Đổi bảng màu hay màu nhấn không làm mất
khung phim 3D. Tắt **Chiều sâu 3D** để dùng khung phẳng, hoặc bật **Giảm chuyển động** để giữ khung xếp lớp đứng yên.
Lựa chọn được nhớ trên trình duyệt này, không đổi phụ đề hay màu của video xuất.

**Ảnh thư viện:** tập và video lẻ tự lấy khung hình từ video gốc hoặc bản xuất; bộ phim
dùng bìa của một tập. Bấm vào bìa (hoặc **Thêm ảnh**) → **Tải ảnh lên** để chọn JPG, PNG
hoặc WebP, tối đa 5 MB. Tập chưa có hình sẽ dùng ảnh bìa đã tải lên của bộ phim, nếu có.
**Dùng bìa tự động** bỏ ảnh riêng đã chọn và quay về cách lấy bìa này.
Bìa chỉ hiển thị trong thư viện; chỉ chủ dự án và người có quyền sửa mới đổi được.

---

## Kiến trúc: frontend và backend tách rời

```
backend/                 API + lõi xử lý (Python, FastAPI)
  main.py                dựng app, ghép router, phục vụ giao diện, CORS
  config.py              đường dẫn, cấu hình, tắt telemetry của thư viện
  api/                   router HTTP theo miền — chỉ nhận và trả JSON
    system  tts  media  jobs  films  projects  deps
  core/                  lõi xử lý, không biết gì về HTTP — gọi được từ CLI, test hay server
    asr  align  diarize  gender  translate  budget  duration  dubbing  media
    pipeline  metrics  subtitles  languages  jobs  hf_cache  setup_ffmpeg
  store/                 lưu trữ JSON: films  projects  series
frontend/                giao diện tĩnh HTML/CSS/JS, không cần build
  index.html  config.js  (config.js: địa chỉ backend, window.VSUB_API_BASE)
  css/                   style.css, appearance.css
  js/                    theme-state (trước CSS) → core → theme → boot → films → source → setup → ai → progress → minutes → editor → hardsub → dubbing → timeline → export → prefs → main
                         (theme-state.js khôi phục diện mạo; theme.js điều khiển bảng cài đặt;
                          icon là SVG nội tuyến trong index.html, gọi bằng icon('tên') ở core.js)
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
uv sync --extra cuda --extra separate  # + bỏ giọng gốc, giữ nhạc nền (Demucs; chạy CPU ~bằng thời lượng video)
```

Cài tất cả:

```bash
uv sync --extra cuda --extra ai --extra offline --extra tts --extra clone --extra diarize --extra separate
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
| `--host 0.0.0.0` | lắng nghe LAN; để đăng nhập qua Wi-Fi cần thêm chứng thư và khóa HTTPS |
| `--invite` | tạo mã đăng ký thành viên dùng một lần, hết hạn sau 24 giờ, rồi thoát |
| `--no-browser` | không tự mở trình duyệt |
| `--reload` | tự nạp lại khi sửa code (dev) |

### Chạy bằng Docker

```bash
docker compose up -d --build
docker compose exec vsub python run.py --invite
```

Mở <http://127.0.0.1:8000>. Compose dựng hai dịch vụ: ứng dụng và Redis (hàng đợi tác vụ, giữ
trạng thái job qua các lần khởi động lại). Dữ liệu và model tải về nằm trong volume `vsub-data`.
Compose chỉ công bố cổng trên loopback. Không giữ `VSUB_LOOPBACK_PUBLISHED=1` nếu thay cấu hình
đó để mở mạng LAN; khi triển khai cho điện thoại dùng HTTPS.

Ảnh mặc định có lồng tiếng, dịch AI và hàng đợi nhưng **không có torch** (nhẹ hơn ~2,5 GB), nên
chưa có nhận diện người nói và nhân bản giọng — tách giọng nam / nữ thì vẫn có. Muốn đủ:

```bash
VSUB_EXTRAS="--extra queue --extra tts --extra ai --extra diarize --extra clone" HF_TOKEN=hf_... docker compose up -d --build
```

Trong container không có GPU NVIDIA trừ khi cài NVIDIA Container Toolkit; Whisper sẽ chạy bằng CPU.

### Bộ cài Windows (không cần Docker, không cần gõ lệnh)

```powershell
powershell -ExecutionPolicy Bypass -File installer\windows\build_exe.ps1
```

Lệnh trên biên dịch hai tệp bằng `csc` có sẵn của .NET Framework 4 (Windows 10/11, không cần Visual Studio)
vào `installer/windows/dist/`:

| Tệp | Làm gì |
|---|---|
| `VSubStudio_Setup.exe` (~23 MB) | Bộ cài: chép mã nguồn + `uv.exe` vào `%LOCALAPPDATA%\Programs\VSubStudio` (không cần quyền quản trị), tạo lối tắt, thêm mục gỡ cài đặt vào Cài đặt → Ứng dụng. Cài im lặng: `/S /D=<thư mục>` |
| `VSubStudio.exe` | Trình khởi động đặt cạnh `run.py` (bản sao ở gốc repo, đã gitignore). Lần đầu hỏi bản đầy đủ (~6 GB) hay gọn (~1,5 GB) rồi chạy `uv sync`; sau đó chạy server, chờ sẵn sàng, mở trình duyệt. Ô *Cho điện thoại cùng Wi-Fi kết nối* khởi động lại với `--host 0.0.0.0` và hiện địa chỉ IP. Đóng cửa sổ là dừng server |

Tệp chưa ký số nên Windows SmartScreen có thể cảnh báo (*More info → Run anyway*).

### Ứng dụng Android

`mobile/android/` là ứng dụng khách (Java, không AndroidX, Android 7.0+): lưu địa chỉ máy tính đang chạy
VSub Studio, mở giao diện điện thoại trong WebView, cho chọn video trong máy để tải lên và lưu video kết quả
vào thư mục Download. Nhận dạng, dịch, lồng tiếng vẫn chạy trên máy tính (cần GPU).

```powershell
cd mobile\android
.\gradlew.bat assembleRelease      # cần JDK 17 + Android SDK; APK ở app\build\outputs\apk\release\
```

**Qua USB (không cần chứng thư):** chạy `uv run python run.py` trên máy tính, bật gỡ lỗi USB
trên điện thoại, kết nối cáp và chạy `adb reverse tcp:8000 tcp:8000`. Trong app nhập `localhost:8000`.
**Qua Wi-Fi:** dùng reverse proxy HTTPS hoặc `uv run python run.py --host 0.0.0.0 --ssl-certfile cert.pem --ssl-keyfile key.pem`.
Nhập `https://ten-may:8000` khớp với chứng thư được Android tin cậy. Chỉ bật ô Wi-Fi trên launcher
cũ chưa đủ để đăng nhập. App không gửi mật khẩu qua HTTP mạng LAN.

### Tài khoản và dữ liệu

Chủ máy chạy `uv run python run.py --invite`, đưa mã trực tiếp cho người cần mời. Mở studio,
chọn **Có mã mời? Đăng ký**, nhập tên tài khoản và mật khẩu (10–128 ký tự). Lần sau chỉ cần đăng nhập.
Sau khi đăng nhập, mở **Trang cá nhân** để xem ngày tham gia và quyền tài khoản. Chọn **Chỉnh sửa hồ sơ**
để cập nhật tên hiển thị, email liên hệ, công việc trong ê-kíp và giới thiệu. Các mục này không bắt buộc;
email không dùng để đăng nhập hoặc khôi phục mật khẩu. Đổi mật khẩu cần mật khẩu hiện tại; các phiên khác phải đăng nhập lại.
Tài khoản mới là **thành viên**, không có quyền đọc phim của người khác. Để thiết lập admin đầu tiên,
chủ máy chạy `uv run python run.py --make-admin TEN_DANG_NHAP` cho một tài khoản đã đăng ký rồi tải lại trang.
Không có mật khẩu admin mặc định. Admin mở **Quản trị studio** (`/#admin`) từ thư viện hoặc trang cá nhân.
Bảng điều hành riêng có ba mục **Tài khoản**, **Nhóm sản xuất** và **Dự án phim**; các số đếm lấy từ máy chủ.
Admin có thể cấp mã đăng ký, đổi quyền tài khoản,
khóa/mở khóa hoặc giao bộ phim cũ cho trưởng nhóm. Khóa tài khoản chấm dứt các phiên đang dùng.

**Làm chung một dự án:**

1. Trong **Nhóm & mã mời**, tạo nhóm. Mở **Quản lý nhóm → Tạo mã nhóm**, gửi riêng mã `TM-…` cho đồng đội.
2. Tại thư viện, **Tạo dự án phim → Không gian dự án** và chọn nhóm. Nếu làm một mình, chọn **Cá nhân**.
3. Chủ dự án vào **Cộng tác**, chọn **Chỉ xem** hoặc **Biên tập** và tạo mã `PJ-…`. Người nhận đã đăng nhập dùng
   **Nhóm & mã mời → Tham gia bằng mã**. Với phim của nhóm, dùng mã nhóm trước, rồi mã dự án. Cùng nhóm
   không tự nhìn thấy phim của nhau. Mã đăng ký, nhóm và dự án không thay thế nhau; mỗi mã dùng một lần trong 24 giờ.

| Vai trò | Quyền |
|---|---|
| Quản trị studio | Quản lý tài khoản, mọi nhóm và mọi dự án, kể cả thư viện cũ chưa phân công |
| Trưởng nhóm | Mời/gỡ thành viên nhóm; không tự xem hoặc quản lý phim do thành viên khác tạo |
| Chủ dự án | Xử lý, mời/gỡ cộng tác viên, đổi quyền, đổi tên, xóa tập và bộ phim |
| Biên tập | Xem, thêm tập, sửa kịch bản/phân vai, dịch và xuất; không xóa dự án hay cấp quyền |
| Chỉ xem | Đọc kịch bản, phát video, tải các bản đã xuất; không chỉnh sửa hoặc chạy job trên dự án |

Gỡ thành viên khỏi nhóm thu hồi quyền ở các phim của nhóm; tham gia nhóm lại vẫn cần mã dự án mới.
Mã chưa dùng có thể thu hồi trong **Cộng tác**. Hai biên tập viên lưu cùng một bản kịch bản: người
lưu sau được báo xung đột và phải mở lại để đối chiếu, không tự gộp văn bản. Bộ nhớ dịch và
thuật ngữ học từ kịch bản được tách theo dự án. Khi nâng cấp, **dừng tất cả server cũ** dùng cùng `data`
trước khi chạy bản mới: tiến trình cũ không thực thi quyền theo nhóm.

SQLite qua SQLAlchemy, tệp `data/vsub.db`, bật khóa ngoại và WAL. Bảng `films`, `episodes`,
`characters`, `voices`, `translation_memory` giữ dữ liệu nghiệp vụ; `studio_members`, `login_sessions`,
`studio_invites` lưu thành viên, phiên và mã mời. CSDL không chứa mật khẩu thô, mã mời hay token
phiên thô. `teams`, `team_members`, `film_members`, `collaboration_invites`, `job_scopes` và
`upload_owners` lưu phạm vi cộng tác. Video lẻ cũ chỉ hiện cho admin; có thể gán rõ ràng vào một tập.
Phiên hết hạn sau 7 ngày hoặc ngay khi đăng xuất. Nâng cấp tạo bảng và chỉ mục tại chỗ;
không nhận quyền sở hữu dự án cho tài khoản đầu tiên. Video gốc ở `data/uploads`, kịch bản,
track và file xuất ở `data/jobs`: khi sao lưu toàn bộ studio, dừng server rồi sao lưu cả `data`,
không chỉ chép một file `.db` đang mở.

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
**tạo sẵn từng tập** kèm tên và thời lượng. Chỉ bộ cá nhân tự nhận video lẻ của chính bạn có link khớp;
bộ nhóm không tự lấy video từ thư viện riêng.

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
cũng vậy. Dán riêng địa chỉ video (ví dụ `youtu.be/…` cũng được), rồi bấm **Kiểm tra link**, **Enter** hoặc **Tiếp tục** để xem danh sách phần kèm thời
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

**Dịch theo ngữ cảnh.** Engine AI không dịch rời từng lô nữa:

| Việc | Cách làm |
|---|---|
| **Đọc lướt kịch bản** | Trước khi dịch, AI đọc cả kịch bản một lượt và tự ghi chú thể loại, nhân vật, quan hệ, xưng hô, tên riêng. Ghi chú đi kèm **mọi** lô nên tên và xưng hô thống nhất từ đầu tới cuối (tắt được ở bước 2) |
| **Ngữ cảnh quanh mỗi lô** | Mỗi lô mang theo 8 câu vừa dịch xong và 4 câu sắp tới — câu đáp cộc lốc, đại từ được hiểu theo câu trước nó |
| **Biết ai đang nói** | Đã tách giọng thì từng câu được gắn tên vai kèm giới và nhóm tuổi, để chọn xưng hô (anh / chị / em, chàng / thiếp, ta / ngươi…) |
| **Tên riêng tiếng Trung** | Chuyển sang âm Hán-Việt, không để pinyin |
| **Bộ thuật ngữ cho mọi engine** | Với Google / MyMemory / NLLB, thuật ngữ được cài thẳng vào câu gốc trước khi dịch (`朱大生 = Chu Đại Sinh`) |
| **Bộ nhớ dịch** | Câu bạn sửa tay ở bước 4 rồi xuất được ghi nhớ. Lần sau gặp lại đúng câu đó thì dùng bản của bạn (engine nào cũng vậy); câu gần giống thì đưa cho AI làm mẫu |

Riêng Trung → Việt, bước 2 có **Tra Hán Việt từ kịch bản**. Sau khi mở dự án hoặc nhập lời gốc,
có thể xem mục từ theo tên người, địa danh, xưng hô, danh từ và thành ngữ, chọn những mục cần đưa vào
ô thuật ngữ rồi sửa. Tool tự nhận họ đơn/họ kép trong lời giới thiệu (ví dụ `我叫欧阳明`),
dùng cách đọc theo địa danh (`重庆` → Trùng Khánh), dịch nghĩa thay vì ghép âm với thành ngữ
(`锦衣玉食` → ăn ngon mặc đẹp). Tên suy ra chỉ dùng trong kịch bản hiện tại; không tự ghi vào bộ nhớ
toàn cục chỉ vì được đoán một lần. ASR nghe sai hoặc thành ngữ chưa có mục vẫn cần người duyệt.

Đo trên bộ gold 271 câu (phim cổ trang zh→vi, so với bản dịch tham chiếu; mỗi cấu hình chạy một lần):

| Cấu hình | BLEU | chrF | Câu còn tên pinyin |
|---|---|---|---|
| Google | 7,9 | 28,9 | 8 % |
| Google + bộ thuật ngữ | 10,2 | 32,6 | 1 % |
| LLM, dịch rời từng lô (bản cũ) | 38,9 | 59,4 | 0 % |
| LLM + ghi chú bối cảnh và thuật ngữ viết tay (bản cũ) | 40,3 | 62,7 | 0 % |
| LLM + đọc lướt tự động + ngữ cảnh lô, **không** ghi chú tay | 41,6 | 63,3 | 0 % |

Bản có ngữ cảnh dài hơn tham chiếu 8 % (bản cũ 2 %) — bật **Rút gọn câu vượt khung thời gian** nếu định lồng tiếng.
Đo lại: `PYTHONPATH=. python data/_bench/eval_context.py ai_auto`.

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

1. Nếu câu cuối chưa tới 85% video và VAD đang bật, nghe lại không VAD và bổ sung đoạn mới, không bỏ lời đã nhận ra.
2. Dùng VAD tìm tiếng nói trong khoảng trống từ 0,65 giây giữa các từ, kể cả giữa phim. Nghe lại tối đa 40 đoạn nghi có lời, lọc chữ lặp và kết quả thiếu tin cậy.
3. Đoạn còn nghi có tiếng nói được lưu với dự án để nghe lại ở bước 4. Đây là gợi ý, không phải kết luận nhạc nền là lời thoại. Video có câu ở giây cuối **không** có nghĩa là đã nhận ra hết lời.

Với phim có nhạc lấn giọng, bật **Tách nhạc nền trước khi nghe giọng** để Whisper và bước nhận diện vai nghe rãnh giọng do Demucs tách. Nếu tách thất bại, tool dùng tiếng gốc và ghi lý do vào nhật ký.

### Bước 3 — Xử lý

Xem tiến độ từng bước và log thời gian thực. Có thể bấm **Huỷ** bất cứ lúc nào.

### Bước 4 — Biên tập & xuất

- **Kịch bản theo phút:** chọn khoảng trong danh sách (kể cả phút trống) hoặc bật **Theo video**. Phút có lời chưa dịch hoặc có đoạn cần nghe được đánh dấu. Câu vắt qua phút xuất hiện trong cả hai khung nhìn nhưng chỉ xuất/đọc một lần.
- Bấm **Thêm câu** hoặc một mốc nghi thiếu lời, nhập mốc bắt đầu/kết thúc, lời gốc và/hoặc bản dịch rồi **Áp dụng**. Bấm mốc giờ trên câu để chỉnh; **Xóa** chỉ xóa câu đang chọn. **Lưu kịch bản** để mở lại mà không phải xuất video.
- Nếu đã bổ sung lời gốc, bấm **Dịch câu thiếu** để dịch các dòng trống trong phút đang xem bằng engine ở bước 2. Các dòng đã có bản dịch không bị viết lại.
- Bản dịch gắn với đúng dòng nguồn; engine AI được đọc các dòng lân cận nhưng phải trả về theo số dòng. Nếu vẫn thiếu sau khi thử lại, dòng được ghi **Chưa dịch**, không coi lời gốc là bản dịch. Bản lồng tiếng không tự đọc nguyên ngữ thay chỗ trống.
- Bố cục **bàn dựng phim**: màn hình xem bên trái, danh sách thoại bên phải, **dòng thời gian** chạy ngang bên dưới
- Dòng thời gian: mỗi nhân vật một rãnh, mỗi dòng phụ đề một khối. Kéo khối để dời mốc giờ, kéo mép để co giãn,
  kéo sang rãnh khác để đổi vai; bấm chỗ trống để tua. Ctrl + lăn chuột để thu phóng; Alt + ←/→ dời khối 0,1 giây
- Rãnh **Lồng tiếng** vẽ thời lượng đọc dự đoán của từng câu (cùng hàm với lúc xuất) và tô đỏ phần đọc tràn khung —
  thấy trước khi xuất, sửa chữ hay kéo mốc giờ là tính lại
- Rãnh sóng âm: tiếng gốc, hoặc giọng gốc và nhạc nền riêng nếu dự án đã tách giọng
- Bấm một dòng để tua video tới đúng chỗ đó
- Sửa trực tiếp lời gốc và bản dịch trong ô
- Chỉ số **cps** (ký tự/giây) chuyển vàng khi > 22 — dấu hiệu phụ đề trôi quá nhanh
- Đổi font, cỡ chữ, màu, viền, vị trí — xem trước ngay trên video
- **Lệch giờ** để đẩy toàn bộ phụ đề sớm/muộn nếu bị lệch tiếng

Phím tắt: `Space` phát/dừng · `←` `→` nhảy dòng trước/sau.

### Lồng tiếng (tuỳ chọn)

Ở bước 4, mở **Duyệt kịch bản sau dịch**. Mỗi câu đọc có mốc giờ, vai và dòng phụ đề
đối chiếu. Mỗi dòng được đọc ở mốc riêng; không ghép lời của các dòng sau để đọc sớm.
Sửa câu thiếu bản dịch hoặc còn chữ chưa dịch rồi bấm **Dựng lại**.
**Xem & nghe** phát riêng câu nháp trên hình gốc, không lưu phụ đề, không trộn nhạc nền
và không cần xuất video. Bấm **Sửa tiếp** để quay lại ô đang sửa.
Phần tiếng vừa nghe được giữ riêng trong dự án. Nếu giữ nguyên lời, vai và giọng,
bản xuất dùng lại lần đọc đó, kể cả khi đóng rồi mở lại dự án. Nếu phát âm chưa
ưng, bấm **Tạo lượt đọc khác** ở chính dòng đó rồi duyệt lại; bản đã duyệt trước
đó không bị thay chỉ vì một người khác đang nghe thử. Đổi tốc độ chỉ
canh lại cùng bản thu; âm lượng và nhạc nền được trộn ở bước xuất.

Khi đã hài lòng, bấm **Duyệt kịch bản này**, rồi bật **Lồng tiếng**. Máy chủ lưu lời đã
duyệt cùng phụ đề theo dự án; bản xuất dùng đúng những câu đó, không tự rút gọn thêm.
Đổi lời, mốc, vai, giọng, phong cách hoặc tốc độ thì phải duyệt lại. Nếu bộ đọc
chỉ sinh tiếng bật, im lặng hoặc hỏng sau khi thử lại, công cụ báo số dòng và
dừng thay vì xuất một video thiếu tiếng.

| Tuỳ chọn | Ý nghĩa |
|---|---|
| **Giọng đọc** | 14 giọng dựng sẵn (nam/nữ × Bắc/Trung/Nam × tin tức/tự nhiên/kể chuyện) |
| 🧬 **Nhân bản giọng trong video** | Cắt 4–8 giây có tiếng nói từ chính video rồi bắt chước giọng đó |
| **Phong cách đọc** | Tự nhiên · Bản tin · Đọc truyện |
| **Tiếng gốc của video** | **Bỏ giọng gốc, giữ nhạc nền và tiếng động** (mặc định, cần `--extra separate`): tách giọng khỏi nhạc bằng Demucs, chỉ còn giọng mới trên nền nhạc; mẫu nhân bản giọng cũng cắt từ phần giọng đã sạch nhạc. Hai cách khác: *Giữ nguyên tiếng gốc, hạ nhỏ khi có người đọc* và *Thay hẳn tiếng gốc* |
| **Tự cân âm lượng** | Chuẩn hoá giọng đọc lên sát mức tối đa, và hạ nền thêm nếu tiếng gốc còn to quá |
| **Tiếng gốc chỉ nhỏ lại khi có người đọc** | Ducking: đoạn không ai đọc vẫn nghe nguyên nhạc/tiếng động |
| **Âm lượng giọng đọc** | Nhân thêm lên mức tool đã tự cân (mặc định 100%). Kéo lên nếu vẫn thấy lép |
| **Âm lượng tiếng gốc** | **Mức tối đa** của tiếng gốc — mặc định 45%. Tool chỉ được hạ xuống, không tự nâng lên |
| **Tăng tốc tối đa** | Câu dịch dài hơn khung giờ sẽ được đọc nhanh hơn (giữ nguyên cao độ) tới mức này |

Bấm **Xem & nghe câu đang chọn** để nghe trên hình trước khi xuất.

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
| **Nhãn nhân vật** | `S1`, `S2`… đánh số theo **tổng thời gian nói giảm dần** trong video hiện tại. `S1` không phải tên người thật và không nhất thiết là cùng một người ở tập khác |
| **Gán dòng cho vai** | Theo **độ chồng lấn thời gian lớn nhất**. Dòng vắt qua hai người thì lấy bên chiếm nhiều hơn |
| **Dòng không rõ ai nói** | Thường là phụ đề trên nền nhạc — đọc bằng giọng ở ô "Giọng đọc" chung |
| **Mẫu nhân bản** | **Ghép từ nhiều câu của đúng vai đó** (tới ~8–10 giây), mỗi khúc cắt gọn trong mốc giờ của một câu, ưu tiên câu **không sát lượt của người khác**; có mô hình véc-tơ giọng thì chọn những câu tiêu biểu nhất và loại câu lạc giọng. Không gom đủ 3 giây thì quay về cắt một đoạn liền như trước |
| **Độ to theo thoại gốc** | Khi đã tách giọng gốc khỏi nhạc: câu gốc nói to thì câu lồng to hơn, nói khẽ thì nhỏ hơn (theo 60 % độ lệch so với mức thường của chính vai đó, chặn ±4 dB) |
| **Mẫu không lấy câu trầm** | VieNeu-TTS đọc thấp hơn mẫu của nó 2–3 nửa cung, nên mẫu ghép chỉ lấy các câu có cao độ (F0) **từ tầm giọng của vai trở lên** — bản đọc bớt trầm hơn người thật. Không còn đủ 3 giây sau khi lọc thì dùng lại mọi câu |
| **Kịch bản lồng tiếng có dấu câu** | **Duyệt kịch bản sau dịch** giữ một câu đọc cho từng mốc và vai, bổ sung dấu câu khi cần. Khi xuất, giọng đọc và file `<tên>.kichban.txt` dùng cùng bản đã duyệt. Bộ dựng cụm câu độc lập (`POST /api/tts/script` không có `project`) vẫn có thể nối các mảnh có dấu chấm / phẩy / hỏi theo câu gốc; phép đo cũ trên 4 dự án giảm từ 227/291 chỗ nối thiếu dấu xuống 0. |
| **Báo vai nhân bản lệch tone** | Khi đã tách giọng gốc khỏi nhạc: lúc lồng tiếng, đo cao độ từng câu đọc so với tầm giọng gốc của vai. Vai nào lệch từ 4 nửa cung trở lên (trung vị, ít nhất 3 câu) thì nhật ký báo rõ, để bạn đổi sang giọng dựng sẵn cho vai đó |
| **Tone giọng theo thoại gốc** (thử nghiệm, mặc định tắt — bật bằng `dub.match_pitch`) | Đo trên tập phim 16 phút, 4 vai: lệch tầm giọng giảm 2,0 → 0,4 nửa cung nhưng độ giống giọng (cosine WeSpeaker) tụt 0,68 → 0,45, với cả bốn cách dịch cao độ đã thử (`data/_bench/pitch_variants.py`), nên chưa bật mặc định. Cách làm: khi đã tách giọng gốc khỏi nhạc và vai dùng giọng nhân bản, đo cao độ (F0) của vai trong tiếng gốc, rồi nâng/hạ từng câu lồng về tầm đó; câu gốc lên giọng hay xuống giọng thì câu lồng nhích theo 50 % (chặn ±2 nửa cung). Mỗi câu chỉnh tối đa 3 nửa cung, giữ nguyên độ dài và formant (ffmpeg `rubberband`); lệch dưới nửa nửa-cung thì để yên. Đây là xử lý tín hiệu, không huấn luyện lại VieNeu-TTS |
| **Vai không cắt được mẫu** | Tự chuyển sang giọng dựng sẵn, có báo rõ — không làm hỏng cả bản lồng tiếng |
| **Biết trước số vai** | Điền số **người có thoại**, từ 1 đến 20, tính cả người dẫn đọc ngoài hình. Không chắc thì để trống; đoán sai số có thể gộp hai vai hoặc tách một vai thành hai |

> Không phụ thuộc ngôn ngữ: bước này chỉ đọc đặc trưng âm học của giọng, nên phim Trung, Hàn,
> Nhật, Anh hay bất kỳ tiếng nào cũng dùng được y như nhau.

**Chọn cách nhận diện ở bước 2:**

1. **Chạy ngay không cần tài khoản:** trong khung **Nhận diện người nói**, bấm **Dùng cách không cần token**.
   App tắt phân đoạn pyannote và bật **Tách giọng nam / nữ, nhiều người, tuổi**. Chế độ này nhóm giọng theo từng dòng phụ đề;
   WeSpeaker là model công khai (lần đầu có thể cần tải). Nếu không dùng được WeSpeaker, app dùng cao độ;
   hai giọng giống nhau dễ bị gộp. Số người nhập ở khung pyannote không áp dụng cho cách này.
2. **Muốn phân đoạn theo lượt nói:** trên máy chủ, cài nhóm tùy chọn nếu còn thiếu:
   `uv sync --inexact --extra diarize` rồi khởi động lại VSub. Đăng nhập Hugging Face, mở đúng link model
   trong app và đồng ý điều khoản. Bản pyannote 4.x mặc định dùng [Community-1](https://huggingface.co/pyannote/speaker-diarization-community-1);
   bản 3.x dùng [diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1) cùng
   [segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0).
3. Tạo [token chỉ đọc](https://huggingface.co/settings/tokens) của **cùng tài khoản**. Token fine-grained
   phải có quyền đọc các model gated đã được duyệt. Dán vào ô mật khẩu **trên máy chủ VSub bạn tin cậy**
   hoặc đặt biến môi trường `HF_TOKEN` trước khi mở app. Không gửi token qua chat. Bấm **Kiểm tra quyền tải**:
   máy chủ chỉ hỏi thông tin tệp, không gửi tiếng hay tải trọng số. Có quyền đọc chưa phải đã tải xong.
   Lỗi 401/403: kiểm tra tài khoản, trạng thái duyệt và quyền token; lỗi mạng: kiểm tra Internet của **máy chủ**.
4. Bấm **Bắt đầu xử lý** (không phải *Chỉ dịch lại*). Nếu biết clip có hai người đối thoại và không ai khác
   lên tiếng, nhập `2`; nếu không, để trống. Nhạc lấn thoại thì cân nhắc **Tách nhạc nền trước khi nghe giọng**.
   Ô **Gợi ý từ khoá cho Whisper** chỉ giúp chép đúng chữ của tiếng gốc, không đặt tên vai.
5. Ở bước 4, nghe lại các mốc chưa chắc trong nhật ký, nhất là đoạn nói chồng hoặc quá ngắn; sửa nhãn vai ở từng dòng.
   Chọn giọng dựng sẵn cho từng vai → **Xem & nghe** → **Duyệt kịch bản này** trước khi xuất.

### 👫 Tách giọng nam / nữ — không cần cài thêm gì

Bật mặc định ở bước 2 (**Tách giọng nam / nữ**). Tool đo cao độ giọng (F0) của từng câu thoại
ngay trên đường tiếng của video — dưới 165 Hz là giọng nam, từ đó trở lên là giọng nữ — rồi:

| Trường hợp | Làm gì |
|---|---|
| **Không bật nhận diện người nói** | Chia các dòng thành hai vai *Nam* / *Nữ* (`S1`, `S2`, vai nói nhiều hơn là `S1`) |
| **Có bật nhận diện người nói** | Giữ nguyên các vai pyannote tìm ra, chỉ gắn thêm giới tính cho từng vai (gộp cao độ mọi câu của vai đó) |
| **Câu quá ngắn / lẫn nhạc** | Không đoán, để trống — đọc bằng giọng chung |
| **Có model WeSpeaker (extra `diarize`)** | Chia tiếp nhiều người cùng giới (*Nam 1*, *Nam 2*, *Nữ 1*…, tối đa 6 mỗi giới) bằng véc-tơ giọng, không cần token; ngưỡng gộp tự thích nghi theo độ sạch của thoại. Cụm bị chia nhầm giới (nam quát to vượt 165 Hz) gộp về cụm khác giới nó giống hẳn; mọi câu từ 0,4 s — kể cả lời gọi ngắn — về tâm giọng gần nhất; cụm dưới 1,5 % tổng thoại dồn vào cụm gần nhất |

Đo bằng `data/_bench/speaker_bench.py` (trích đoạn 86 giây có nhãn tay theo mạch truyện, 6 giọng dựng sẵn, hai video dài):

| | Cách cũ | Cách mới |
|---|---|---|
| Trích đoạn 86 giây (3 nhân vật, 43 câu) | 2 vai, đúng 38/43 câu — hai vai nữ bị gộp | **3 vai, đúng 40/43 câu** tự động; còn 3 câu nhầm giữa hai vai nữ |
| 6 giọng dựng sẵn | 7 vai, đúng 93,3 % | **6 vai, đúng 100 %** |
| Video 16 phút / 13 phút | 12 vai (4 / 2 vai dưới 5 câu) | 9 / 10 vai (0 / 1 vai dưới 5 câu) |

**Nhóm tuổi:** chỉ tự đoán được *Trẻ em* (cao độ nam ≥ 215 Hz, nữ ≥ 285 Hz). *Cao tuổi* không đoán được từ cao độ nên chọn tay ở bảng vai (nút Tuổi bên cạnh nút Nam/Nữ).

Sang bước 4, bảng **Giọng cho từng nhân vật** mặc định **nhân bản chính giọng của vai đó trong
phim** (khi đã cài `--extra clone`); chưa cài thì chọn giọng có sẵn **đúng giới tính** (vai nam → giọng
nam, vai nữ → giọng nữ, hai vai cùng giới thì hai giọng khác nhau). Đoán sai giới tính thì:

- bấm nút **Nam / Nữ** cạnh tên vai để đổi — vai đang dùng giọng có sẵn sẽ được đổi sang giọng đúng giới mới;
- ở từng câu, chọn **nhãn vai** để chuyển câu sang vai khác hoặc **+ Tạo vai mới** nếu hai người bị gộp.

**Dự án cũ chưa có vai:** ở bước 4, bấm **Dòng thời gian → Phân giọng**. Tool ưu tiên rãnh
giọng gốc đã tách, kể cả rãnh từ lần xuất trước, và chỉ lưu nhãn vai; không chạy lại Whisper hay dịch lại.
Nếu hai giọng giống nhau, chọn đúng vai cho một hoặc hai câu nghe rõ, bấm **Lưu kịch bản**, rồi
**Phân giọng** lại. Các câu đã gán tay được giữ làm mẫu. Khi không có model WeSpeaker, chỉ phân
theo cao độ; khi đó vẫn có thể tạo và gán vai bằng tay.

Đo trên trích đoạn 86 giây của video kiểm thử (một nam, một nữ đối thoại): 31 dòng được xếp vai nữ,
12 dòng vai nam; nghe lại đường lồng tiếng, 39/43 dòng có cao độ đúng giới tính của vai được gán.

Giới hạn: cao độ không phân biệt được hai người **cùng giới** (cần nhận diện người nói), giọng trẻ em
thường rơi vào nhóm nữ.

**Giọng giống giọng gốc đến đâu.** Đo bằng véc-tơ đặc trưng giọng (pyannote WeSpeaker, cosine, càng
cao càng giống; hai vai gốc so với nhau được 0,34) trên cùng trích đoạn — script
`data/_bench/voice_similarity.py`:

| Cách chọn giọng | Vai nữ | Vai nam | Whisper nghe đúng |
|---|---:|---:|---:|
| Giọng có sẵn đúng giới (Trúc Ly / Minh Đức) | 0,41 | 0,37 | 16/17 câu |
| Giọng có sẵn **gần cao độ gốc nhất** (Đoan Trang / Quang Sơn) | 0,26 | 0,34 | — |
| **Nhân bản giọng từ video** (mặc định) | **0,43** | **0,55** | 15/17 câu |
| Nhân bản rồi kéo cao độ về đúng cao độ gốc (`rubberband`) | 0,31 | 0,19 | — |

Mẫu ghép so với mẫu cắt một đoạn (cosine WeSpeaker với giọng gốc của vai, TTS đọc cùng 6 câu;
`data/_bench/ref_compare.py`, mỗi cấu hình chạy một lần nên chênh lệch nhỏ có thể là nhiễu):

| Video | Độ thuần của mẫu | Giọng đọc giống giọng gốc |
|---|---|---|
| 16 phút, 6 vai nói nhiều nhất | 0,74 → **0,90** | 0,60 → **0,69** (5 vai tăng, 1 vai giảm 0,05) |
| Clip 86 giây, 2 vai | 0,72 → **0,90** | 0,61 → **0,69** (1 vai tăng 0,17, 1 vai giảm 0,02) |

Chọn câu theo cao độ (tập 16 phút, 6 vai nói nhiều nhất, TTS đọc cùng 6 câu; `data/_bench/pitch_compare.py`,
mỗi cấu hình chạy một lần và TTS có ngẫu nhiên nên chênh lệch nhỏ ở từng vai có thể là nhiễu):

| | Mẫu lấy mọi câu | Mẫu chỉ lấy câu từ tầm giọng trở lên |
|---|---|---|
| Bản đọc lệch tầm giọng gốc (nửa cung, trung bình \|.\|) | 3,82 | **3,00** |
| Giọng đọc giống giọng gốc (cosine) | 0,684 | **0,699** |

Không đều giữa các vai: một vai nữ từ lệch 7,3 xuống 2,1; một vai nữ khác vẫn lệch 8 nửa cung (mẫu nào cũng ra
giọng trầm hẳn) và một vai tệ đi 1,4 — vì vậy có thêm bước báo vai lệch tone ở trên.

Hai cách "khớp cao độ" đều làm giọng *kém* giống hơn — chất giọng quan trọng hơn cao độ — nên tool
không dùng. Nhân bản chậm hơn giọng có sẵn (phải cắt mẫu và mã hoá giọng từng vai).

### 🔲 Che phụ đề có sẵn trong video

Phim tải về hay có sẵn phụ đề tiếng gốc nung vào hình; nung thêm phụ đề tiếng Việt thì hai dòng chữ
chồng lên nhau. Lúc phân tích, tool **dò dải phụ đề cũ** (bước *Dò phụ đề có sẵn trong hình*, vài
giây); dự án làm từ trước thì tự dò khi mở ở bước 4.

Dò ra thì ở bước 4, mục **Kiểu phụ đề → Che phụ đề có sẵn trong video** tự bật: khung mờ trên video là
bản xem trước, phụ đề mới được đặt vào giữa dải đó. Khi xuất **Video nung phụ đề**, dải được làm mờ
(hoặc phủ hộp tối) rồi mới vẽ phụ đề mới lên. Chỉnh được mép trên, chiều cao, bề ngang của dải; nút
**Dò lại** chạy lại bộ dò.

Cách dò: lấy khung hình giữa mỗi câu thoại, đánh dấu điểm giống nét chữ phụ đề (sáng, viền tối, nét
mảnh), rồi tìm dải ngang mà ở hai câu liền nhau đều dày nét chữ **nhưng nét đã đổi** — câu đổi thì chữ
đổi, còn cảnh nền đứng yên. Đo trên 3 video có phụ đề cứng và 2 bản đã cắt bỏ phụ đề: điểm 0,76–0,94 so
với 0,00–0,14, ngưỡng 0,4; dò đúng cả 5. Logo / tên kênh đứng yên không bị che nhầm.

### ⏱ Vừa khung thời gian: dự đoán trước, rút gọn trước, nén sau cùng

Bản dịch tiếng Việt thường dài hơn lời gốc. Cách cũ: dịch xong, lúc lồng tiếng câu nào dài
quá khung thì **nén âm thanh** (`atempo`) — giọng gấp và máy móc. Đo thật trên một clip 392 s:
48/69 câu phải nén, nén tối đa 1,48×.

Cách mới, bật bằng tuỳ chọn **Rút gọn câu vượt khung thời gian** ở bước 2 (`budget_loop`) và
**Rút gọn câu đọc không kịp** ở bước lồng tiếng (`dub.shorten`, mặc định tắt để giữ lời đã duyệt):

```
dịch  →  dự đoán số giây TTS sẽ đọc (mô hình HP-3) cho từng ĐƠN VỊ ĐỌC (đúng cách lồng tiếng gộp câu)
      →  câu nào vượt: Claude / OpenAI → nhắc AI viết lại ngắn hơn, kèm giới hạn âm tiết (tối đa 2 lượt)
                       Google / NLLB   → bộ luật rút gọn tiếng Việt (`backend/core/shorten.py`):
                                         cụm dài → cụm ngắn cùng nghĩa, bỏ từ đệm, từ chức năng dư,
                                         phó từ mức độ — theo 4 tầng; cần nghe lại sắc thái nếu bật
      →  vẫn vượt thì mới để atempo lo, và log chỉ rõ dòng nào
```

Ở bước 4, **Rút gọn câu đọc không kịp** chỉ đề xuất lời ngắn hơn lúc **Dựng kịch bản**.
Bạn có thể sửa riêng câu đọc rồi nghe thử; lúc xuất không chạy lại bộ rút gọn. SRT, VTT,
phụ đề nung và phụ đề mềm giữ nguyên bản dịch. Tùy chọn ở bước 2 thì khác:
nó được phép làm gọn bản dịch máy trước khi duyệt, nhưng không rút tiếp câu khớp bộ nhớ sửa tay
hoặc khớp nguyên một mục thuật ngữ.

Có thể huấn luyện và thử riêng model **dịch sát nghĩa** (Trung → Việt) và model **viết lời đọc**
(Việt → Việt theo số âm tiết); mỗi model bật hoặc tắt độc lập. Xem [dữ liệu, cách chạy và kết quả
đối chiếu](training/DIALOGUE.md). Đây là hai adapter ngôn ngữ, không phải giọng TTS mới.

Phần huấn luyện nằm trong notebook, xem [training/README.md](training/README.md):

| Việc | Notebook |
|---|---|
| Sinh dữ liệu thời lượng đọc bằng VieNeu-TTS (tự động, không gán nhãn tay) | `training/01_sinh_du_lieu_thoi_luong.ipynb` |
| Huấn luyện mô hình dự đoán thời lượng | `training/02_huan_luyen_duration.ipynb` |

```bash
uv run jupyter lab training/
```

Mô hình lưu ở `data/models/duration_vi.json`; chưa có thì tool dùng ước lượng thô ~4,3 âm tiết/giây.
Với `training/data/seed_vi.txt` (86 câu) chỉ là chạy thử đường ống.

Bản hiện tại học trên **3.674 câu** (Tatoeba tiếng Việt + câu dịch của chính tool, 2 giọng nam + 2 giọng
nữ đọc luân phiên, ~2 giây/câu trên CPU) — `data/_bench/gen_duration.py` rồi `train_duration.py --save`.
Ngoài hồi quy tuyến tính còn học **hệ số tốc độ của từng giọng** (các giọng nhanh chậm khác nhau tới 15 %):

| Đo trên | Ước lượng thô | Không biết giọng | Biết giọng |
|---|---:|---:|---:|
| 367 câu giữ lại | 335 ms | 250 ms | **166 ms** |
| 68 câu lồng tiếng thật (câu gộp dài) | 348 ms | 280 ms | 238 ms |

Mô hình phi tuyến (gradient boosting) cùng đặc trưng không hơn (252 ms) — chỗ nghẽn là giọng. Vòng lặp
rút gọn chạy lúc dịch, *trước* khi chọn giọng, nên hiện dùng bản không biết giọng.

**Khung đo tự động.** Mỗi lần lồng tiếng, tool ghi `data/jobs/<id>/eval.json`: tỉ lệ câu phải nén,
hệ số nén lớn nhất, tổng thời gian tràn, hệ số thời gian thực, kèm nhãn cấu hình C0…C4 (xem
`backend/core/metrics.py`). Gom và in bảng so sánh:

Mở `training/04_khung_do_ket_qua.ipynb` — nó in bảng Markdown dán thẳng vào báo cáo
và xuất kèm CSV.

**Đọc theo câu trọn, không đọc từng dòng phụ đề.** Đây là chỗ quyết định chất lượng.

Phụ đề bị cắt theo **giới hạn ký tự**, không theo ngữ pháp — Whisper tiếng Trung gần như không
trả dấu câu (đo trên một video thật: 18 dấu / 1768 ký tự, 53/69 cue bị cắt vì đủ 28 ký tự, chỉ
8/69 kết ở dấu câu). Bản cũ gom nhiều dòng để dịch rồi chia ngược theo số ký tự, có khi chữ của
người này rơi vào mốc của người khác. Bản hiện tại ưu tiên ranh giới vế/ngắt nghỉ khi tạo dòng;
chỉ nối mảnh ASR trước khi dịch nếu có dấu hiệu nối vế và cùng vai. Không chia lại lời dịch theo số ký tự.

Đọc từng mảnh đó thì TTS xuống giọng và nghỉ ngay giữa từ. Vì vậy tool **nối các mảnh của cùng
một câu lại rồi đọc trọn một lần** trong khung của nhóm. Câu thêm hoặc đặt mốc tay được đọc riêng.
Số đo dưới đây là của phép so sánh trước đây trên video thật
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
vẫn không đủ thì tăng tốc bằng `atempo` (không đổi cao độ) tới `Tăng tốc tối đa`.
Câu sau không mượn lại cùng khoảng nghỉ để vào sớm. Nếu bản đã duyệt vẫn tràn,
công cụ dừng trước khi ghép tiếng và báo dòng cần sửa, kể cả ở cuối video.

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
| `VSUB_DIARIZE_MODEL` | `pyannote/speaker-diarization-community-1` (4.x), `pyannote/speaker-diarization-3.1` (3.x) | Chủ máy có thể chỉ định model phân đoạn tương thích |
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

Server mặc định chỉ nghe ở `127.0.0.1`. Đăng nhập là bắt buộc cả khi mở link video hoặc tải kết quả.
Trên LAN chỉ sử dụng HTTPS; không đưa studio, tài khoản thành viên hay endpoint dùng khóa API của chủ
máy ra Internet công cộng. Khi dùng reverse proxy, chỉ tin header chuyển tiếp từ proxy do bạn quản lý.

Chỉ xử lý video bạn có quyền sử dụng.
