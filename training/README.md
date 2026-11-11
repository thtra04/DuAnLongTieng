# training/ — phần huấn luyện AI

Bốn notebook, chạy theo thứ tự số. Mỗi notebook tự tìm gốc dự án nên mở từ thư
mục nào cũng chạy được.

| Notebook | Hợp phần | Việc | Cần gì |
|---|---|---|---|
| `01_sinh_du_lieu_thoi_luong.ipynb` | HP-3 | Cho VieNeu-TTS đọc từng câu, đo số giây → `data/duration/samples.csv` | Nhóm `tts` |
| `02_huan_luyen_duration.ipynb` | HP-3 | Huấn luyện mô hình dự đoán thời lượng đọc, so với ước lượng thô | Không |
| `03_lora_nllb_dang_thoi.ipynb` | HP-4 | LoRA cho NLLB-200 dịch ràng buộc độ dài — giải thích + dịch thử; huấn luyện thật bằng script, xem dưới | Môi trường huấn luyện riêng, **đã chạy Trung → Việt** |
| `04_khung_do_ket_qua.ipynb` | Khung đo | Gom `data/jobs/*/eval.json` thành bảng C0–C4 (Bảng 5.2) | Không |

## Corpus cho notebook 03

```bash
uv run python training/build_corpus.py --holdout data/_bench/gold/gold.json
```

Ghi `data/corpus/vidub_train.jsonl` (đúng định dạng notebook 03 đọc) từ ba nguồn:
bộ nhớ dịch (câu người dùng đã sửa tay ở bước 4 rồi xuất — `backend/store/memory.py`),
các dự án cũ dịch bằng engine AI (chưng cất tri thức), và file JSONL ngoài qua `--extra`
(ví dụ OpenSubtitles đã lọc). Bản dịch Google không được lấy. `--holdout` loại các câu
thuộc tập kiểm thử để điểm đo không bị rò.

Dưới ~5.000 cặp thì chưa đủ cho LoRA; script tự cảnh báo. Riêng dữ liệu của tool chỉ ra
~50 cặp sạch, nên corpus thật lấy từ OpenSubtitles qua `--extra` (mục HP-4 bên dưới).

## HP-4: huấn luyện LoRA cho NLLB-200 (đã chạy thật, 11/11/2026)

Môi trường riêng trên ổ D — **không dùng `.venv` của app** (app dùng torch CPU, và `uv sync`
trong lúc app đang chạy sẽ hỏng):

```bash
export UV_CACHE_DIR=data/_train_cache/uv HF_HOME=data/_train_cache/hf
uv venv data/_train_venv --python 3.12
uv pip install --python data/_train_venv/Scripts/python.exe torch --index-url https://download.pytorch.org/whl/cu124
uv pip install --python data/_train_venv/Scripts/python.exe "transformers>=4.44,<5" peft datasets sacrebleu sentencepiece accelerate protobuf
```

Bốn bước, mỗi bước một script:

```bash
# 1. Corpus: OPUS OpenSubtitles v2024 vi–zh_CN (372 MB) -> lọc -> 300.000 cặp
curl -L -o data/_opus/dl/vi-zh_CN.txt.zip https://object.pouta.csc.fi/OPUS-OpenSubtitles/v2024/moses/vi-zh_CN.txt.zip
data/_train_venv/Scripts/python -I -X utf8 training/prepare_opus.py data/_opus/dl/vi-zh_CN.txt.zip
# 2. Gộp với dữ liệu của tool, loại tập kiểm thử (chạy bằng .venv của app vì cần SQLAlchemy)
.venv/Scripts/python training/build_corpus.py --extra data/corpus/opus_zh_vi.jsonl --holdout data/_bench/gold/gold.json
# 3. Huấn luyện — dừng êm sau --max-minutes (mặc định 100), chạy lại lệnh này là tiếp tục
data/_train_venv/Scripts/python training/train_nllb_lora.py --origins extra --dev 500
# 4. Đo: NLLB gốc so với NLLB + LoRA
data/_train_venv/Scripts/python training/eval_nllb_lora.py
```

Kết quả nằm ở `data/models/nllb_lora_dangthoi/` (adapter 9,5 MB + tokenizer có 60 token
`<len:1>`…`<len:60>` + `train_meta.json` + `eval_gold.json`). Trên RTX 4060 Laptop 8 GB:
298.499 cặp, 1 epoch, 9.329 bước, 54 phút, loss dev 2,32 → 2,21.

`--origins extra` bỏ các cặp lấy từ dự án cũ: chúng chính là video dùng làm bộ gold, chỉ
khác cách cắt câu. `build_corpus.py` nay loại cả kiểu "gần trùng" đó (`near_holdout`),
nhưng 54 cặp còn sót phần lớn là ASR nghe sai nên vẫn không dùng.

### Số đo

Bộ gold (271 câu thoại cổ trang, 68 đơn vị đọc; mốc: Google BLEU 7,9 / chrF 28,9, LLM 41,6 / 63,3):

| Bản dịch | BLEU | chrF | Vượt khung (đơn vị đọc) | Vượt khung (dòng) |
|---|---|---|---|---|
| NLLB gốc | 5,0 | 22,1 | 6/68 = 8,8 % | 67/271 |
| NLLB gốc + luật rút gọn (HP-5) | 5,0 | 22,1 | 5/68 = 7,4 % | 66/271 |
| NLLB + LoRA, không token | 5,6 | 22,3 | 6/68 = 8,8 % | 71/271 |
| NLLB + LoRA, dịch lại từng dòng với `<len:n>` | 5,9 | 22,0 | 0/68 | 56/271 |
| NLLB + LoRA, bộ siết của app | 5,5 | 20,5 | 0/68 | 51/271 |

Tập dev (500 cặp OpenSubtitles không tham gia huấn luyện; n = số âm tiết bản tham chiếu):

| Bản dịch | BLEU | chrF | Lệch TB (âm tiết) | Trong ±1 âm tiết |
|---|---|---|---|---|
| NLLB gốc | 12,0 | 30,2 | 2,06 | 50,4 % |
| NLLB + LoRA, không token | 13,3 | 30,9 | 1,90 | 55,2 % |
| NLLB + LoRA, `<len:n>` | 13,0 | 31,0 | 1,01 | 81,6 % |
| NLLB + LoRA, `<len:0,7n>` | 12,1 | 28,8 | 1,23 | 73,4 % |

Kết luận trung thực: LoRA **điều khiển được độ dài** (±1 âm tiết: 50 % → 82 %; hết đơn vị
vượt khung trên bộ gold) nhưng **không làm bản dịch hay hơn đáng kể** — BLEU bộ gold
5,0 → 5,6 chưa có ý nghĩa thống kê, chrF đứng yên, và vẫn kém Google. Mới huấn luyện
Trung → Việt; nhóm B (zero-shot, giả thuyết H1) chưa đo.

### App dùng adapter thế nào

`backend/core/translate.py` tự gắn adapter khi `data/models/nllb_lora_dangthoi/adapter_config.json`
tồn tại **và** môi trường của app có `peft` (nằm trong nhóm `offline`:
`uv sync --extra offline`). Chỉ áp cho Trung → Việt; cặp khác tắt adapter, chạy NLLB gốc. Khi bật
"vòng lặp ngân sách" với engine NLLB, câu vượt khung được dịch lại với `<len:n>`; câu nào
không ngắn đi thì rơi về bộ luật HP-5. Tắt hẳn: `VSUB_NLLB_LORA=0`.

## Chạy

```bash
uv run jupyter lab training/
```

Chưa có Jupyter thì cài: `uv pip install jupyterlab`.

Notebook `02` và `04` chạy được ngay bằng dữ liệu sẵn có trong `data/`.
Notebook `01` cần nhóm TTS — thêm `--extra tts` vào lệnh `uv sync` đang dùng.

## Ranh giới với `backend/`

Notebook chỉ lo **thí nghiệm**: sinh dữ liệu, huấn luyện, vẽ bảng. Mọi logic
dùng lại lúc chạy thật đều nằm trong `backend/core/` và có test:

- `backend/core/duration.py` — đặc trưng câu, mô hình, `evaluate()`
- `backend/core/budget.py` — vòng lặp ngân sách thời gian (HP-5)
- `backend/core/metrics.py` — chỉ số, cấu hình C0–C4, gom bảng
- `backend/core/isochron.py` — token ngân sách `<len:n>` (HP-4), dùng chung cho huấn luyện và app

Nhờ vậy sửa notebook không làm hỏng app, và ngược lại mô hình huấn luyện xong
được app nạp thẳng qua `duration.default_model()`.

## Lưu ý khi commit

Xoá hết output trước khi commit (`Kernel → Restart & Clear Output`). Output làm
diff phình to và có thể lộ đường dẫn máy cá nhân. Có test canh việc này.
