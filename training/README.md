# training/ — phần huấn luyện AI

Bốn notebook, chạy theo thứ tự số. Mỗi notebook tự tìm gốc dự án nên mở từ thư
mục nào cũng chạy được.

| Notebook | Hợp phần | Việc | Cần gì |
|---|---|---|---|
| `01_sinh_du_lieu_thoi_luong.ipynb` | HP-3 | Cho VieNeu-TTS đọc từng câu, đo số giây → `data/duration/samples.csv` | Nhóm `tts` |
| `02_huan_luyen_duration.ipynb` | HP-3 | Huấn luyện mô hình dự đoán thời lượng đọc, so với ước lượng thô | Không |
| `03_lora_nllb_dang_thoi.ipynb` | HP-4 | LoRA cho NLLB-200 dịch ràng buộc độ dài — giải thích + dịch thử; huấn luyện thật bằng script, xem dưới | Môi trường huấn luyện riêng, **đã chạy Trung, Nhật, Hàn, Anh → Việt** |
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
5,0 → 5,6 chưa có ý nghĩa thống kê, chrF đứng yên, và vẫn kém Google. Đo lại ngày 21/11
(nạp chung bốn adapter Trung, Nhật, Hàn, Anh): bộ gold ra đúng từng số trên, năm tệp bản dịch
giống hệt bản 11/11. Bảng tập dev ở trên là số 11/11 trên đủ 500 cặp; bảng chéo ở dưới đo lại
trên tập đã loại câu trùng (465 cặp; bản 11/11 trên tập đó: 49,0 % → 81,5 %) và dùng adapter Trung
bản Hán Việt đã thay bản 11/11 (mục "Âm Hán Việt": bộ gold BLEU 5,6 → 6,7).

### Thêm Nhật, Hàn, Anh (20–21/11/2026)

Mỗi ngôn ngữ nguồn **một adapter riêng**, cùng cấu hình và cùng 60 token ngân sách:
`data/models/nllb_lora_dangthoi` (Trung), `…_ja`, `…_ko`, `…_en`. Corpus lấy từ OPUS
OpenSubtitles v2024; bộ lọc của từng thứ tiếng ở `prepare_opus.py` (đơn vị độ dài: Hàn = khối
Hangul, Nhật = kana + kanji, Anh = từ; ngưỡng tỉ lệ đặt ở hai đầu phân bố đo trên 200–300 nghìn cặp đầu).
Pháp, Nga, Thái (nhóm B) chỉ lấy 2.000 cặp để **kiểm thử** — không adapter nào học các thứ tiếng này.

```bash
curl -L -o data/_opus/dl/ko-vi.txt.zip https://object.pouta.csc.fi/OPUS-OpenSubtitles/v2024/moses/ko-vi.txt.zip   # cũng: ja-vi, en-vi
data/_train_venv/Scripts/python -I -X utf8 training/prepare_opus.py data/_opus/dl/ko-vi.txt.zip              # → data/corpus/opus_ko_vi.jsonl
data/_train_venv/Scripts/python -I -X utf8 training/prepare_opus.py data/_opus/fr-vi/fr-vi.txt.zip --max 2000 # nhóm B: fr, ru, th
data/_train_venv/Scripts/python training/train_nllb_lora.py --src ko --dev 500                               # → data/models/nllb_lora_dangthoi_ko
data/_train_venv/Scripts/python training/eval_nllb_lora.py                                                   # bộ gold + bảng chéo
```

| Thứ tiếng | Tệp OPUS | Cặp đọc | Đạt chuẩn | Dùng |
|---|---|---|---|---|
| Trung | vi-zh_CN (372 MB) | 13.474.328 | 7.935.334 (58,9 %) | 300.000 → adapter (11/11) |
| Nhật | ja-vi (45 MB) | 1.588.641 | 1.144.671 (72,1 %) | 300.000 → adapter |
| Hàn | ko-vi (506 MB) | 18.075.521 | 11.867.663 (65,7 %) | 300.000 → adapter |
| Anh | en-vi (952 MB) | 37.005.102 | 22.001.188 (59,5 %) | 300.000 → adapter |
| Pháp (nhóm B) | fr-vi (702 MB) | 25.773.912 | 15.766.232 (61,2 %) | 2.000 để kiểm thử |
| Nga (nhóm B) | ru-vi (665 MB) | 22.337.479 | 14.182.187 (63,5 %) | 2.000 để kiểm thử |
| Thái (nhóm B) | th-vi (540 MB) | 17.001.638 | 12.082.995 (71,1 %) | 2.000 để kiểm thử |

Huấn luyện (RTX 4060 Laptop 8 GB, 1 epoch, batch 16 × tích luỹ 2, 500 cặp dev tách riêng):

| Adapter | Cặp huấn luyện | Bước | Thời gian | Loss dev (bước 1000 → lần đo cuối) |
|---|---|---|---|---|
| Trung, bản Hán Việt (21/11, **đang dùng**) | 357.471 | 11.171 | 50 phút | 2,3214 → 2,1933 |
| Trung, bản 11/11 (đã thay, cất ở `data/models/_ban_cu/`) | 298.499 | 9.329 | 54 phút | 2,3187 → 2,2080 |
| Nhật | 299.500 | 9.360 | 69 phút | 2,4912 → 2,3904 |
| Hàn | 299.500 | 9.360 | 93 phút (CPU bị tranh) | 2,5097 → 2,4104 |
| Anh | 299.500 | 9.360 | 42 phút | 1,8609 → 1,7736 |

### Bảng chéo 7 thứ tiếng — giả thuyết H1 (đo 21/11/2026)

`eval_nllb_lora.py` thử **mọi adapter trên mọi tập kiểm tra**, gồm Pháp, Nga, Thái mà không
adapter nào học. Adapter Trung trong bảng là bản Hán Việt đang dùng (mục "Âm Hán Việt" bên dưới).
Tập kiểm tra: 500 cặp dev mỗi thứ tiếng nhóm A, 500 cặp nhóm B; đã loại mọi câu có bản Việt trùng
dữ liệu huấn luyện của bất kỳ adapter nào (OpenSubtitles gióng cùng một phụ đề Việt với nhiều thứ
tiếng — loại 35 / 49 / 36 / 23 trong 500 câu dev Trung / Nhật / Hàn / Anh, 124 / 150 / 172 trong
2.000 câu Pháp / Nga / Thái). n = số âm tiết bản tham chiếu. **"Phải nén"** = bản dịch dài hơn n
quá 5 % — cùng ngưỡng `budget.TOLERANCE` app dùng để quyết định tăng tốc giọng. Khoảng tin cậy:
`training/bootstrap_cross.py` (bootstrap ghép cặp 1.000 lượt, `data/_bench/nllb_lora_cross_ci.json`).
Đậm = adapter học đúng thứ tiếng đó.

Trong ±1 âm tiết so với n:

| Tập kiểm tra | Cặp | NLLB gốc | Trung + `<len:n>` | Nhật + `<len:n>` | Hàn + `<len:n>` | Anh + `<len:n>` |
|---|---|---|---|---|---|---|
| Trung | 465 | 49,0 % | **83,0 %** | 79,4 % | 74,2 % | 62,6 % |
| Nhật | 451 | 46,3 % | 75,2 % | **82,3 %** | 73,8 % | 55,0 % |
| Hàn | 464 | 40,5 % | 74,8 % | 79,1 % | **76,9 %** | 53,2 % |
| Anh | 477 | 52,0 % | 72,3 % | 65,6 % | 68,3 % | **73,2 %** |
| Pháp (nhóm B) | 500 | 43,0 % | 64,2 % | 63,6 % | 58,2 % | 57,8 % |
| Nga (nhóm B) | 500 | 50,2 % | 73,6 % | 71,4 % | 69,6 % | 62,8 % |
| Thái (nhóm B) | 500 | 47,8 % | 74,2 % | 72,2 % | 67,4 % | 55,8 % |

Phải nén (dài hơn n quá 5 %):

| Tập kiểm tra | Cặp | NLLB gốc | Trung + `<len:n>` | Nhật + `<len:n>` | Hàn + `<len:n>` | Anh + `<len:n>` |
|---|---|---|---|---|---|---|
| Trung | 465 | 43,9 % | **32,3 %** | 21,3 % | 34,2 % | 38,5 % |
| Nhật | 451 | 33,0 % | 25,3 % | **27,3 %** | 28,6 % | 27,7 % |
| Hàn | 464 | 37,7 % | 24,8 % | 28,9 % | **28,2 %** | 35,3 % |
| Anh | 477 | 50,1 % | 35,0 % | 15,5 % | 24,7 % | **36,3 %** |
| Pháp (nhóm B) | 500 | 37,2 % | 27,0 % | 29,6 % | 31,0 % | 33,0 % |
| Nga (nhóm B) | 500 | 44,8 % | 25,8 % | 27,2 % | 31,0 % | 37,6 % |
| Thái (nhóm B) | 500 | 39,6 % | 27,6 % | 23,0 % | 33,2 % | 37,4 % |

chrF (BLEU từng ô ở `data/_bench/nllb_lora_cross.json`):

| Tập kiểm tra | NLLB gốc | Adapter cùng thứ tiếng, không token | Trung + `<len:n>` | Nhật + `<len:n>` | Hàn + `<len:n>` | Anh + `<len:n>` |
|---|---|---|---|---|---|---|
| Trung | 30,1 | 30,8 | **31,1** | 30,2 | 30,7 | 30,4 |
| Nhật | 25,6 | 25,7 | 25,4 | **26,9** | 26,1 | 25,4 |
| Hàn | 26,1 | 26,8 | 27,0 | 27,1 | **27,6** | 26,7 |
| Anh | 40,4 | 41,1 | 39,6 | 36,3 | 39,2 | **41,3** |
| Pháp (nhóm B) | 32,7 | — | 32,7 | 33,1 | 32,8 | 33,4 |
| Nga (nhóm B) | 32,0 | — | 31,6 | 31,6 | 31,6 | 32,3 |
| Thái (nhóm B) | 31,8 | — | 32,6 | 32,7 | 32,9 | 32,9 |

Đọc bảng:

- **Adapter đúng thứ tiếng + token** đưa ±1 âm tiết từ 40–52 % lên 73–83 % (tăng 21–36 điểm,
  có ý nghĩa) mà chrF không giảm — còn tăng 0,8–1,4 (có ý nghĩa ở Trung, Nhật, Hàn; Anh +0,8,
  khoảng [−0,03; 1,6] chưa đủ chắc).
- **Giả thuyết H1 được ủng hộ trên phép đo này.** Dùng cho thứ tiếng chưa học, token vẫn điều
  khiển được độ dài: ở nhóm B, ±1 âm tiết tăng 8–26 điểm và phải nén giảm 2–19 điểm (mọi ô có ý
  nghĩa, trừ adapter Anh trên tiếng Thái: −2,2 [−6,0; 1,6]); chrF không giảm có ý nghĩa ở ô nào.
  Với adapter Trung, Nhật hoặc Hàn, phải nén dưới 35 % trên cả ba cặp giữ ngoài (Trung: 27,0 /
  25,8 / 27,6 %) — tiêu chí MT-5; NLLB gốc là 37,2 / 44,8 / 39,6 %, adapter Anh 33,0 / 37,6 / 37,4 %.
  Khả năng bám độ dài vì vậy gắn chủ yếu với phía tiếng Việt chứ không với ngôn ngữ nguồn đã học.
  Adapter Trung (bản Hán Việt) và Nhật chuyển tốt nhất — trên tiếng Hàn, adapter Nhật còn nhỉnh hơn
  chính adapter Hàn (79,1 % so với 76,9 %); adapter Anh chuyển kém nhất sang các tiếng châu Á (53–63 %
  trên Trung, Nhật, Hàn, Thái). Bản Trung 11/11 chuyển kém hơn bản Hán Việt (Pháp / Nga / Thái:
  52,4 / 63,6 / 65,6 % so với 64,2 / 73,6 / 74,2 %); chưa tách được là nhờ nhiều dữ liệu hơn hay nhờ
  kiểu câu cài sẵn cụm.
- **Chưa đạt MT-4 theo phép đo này:** dù có token, phải nén vẫn 27–36 % (tiêu chí dưới 25 %).
  Token nhắm đúng n nên khoảng một phần ba bản dịch dài hơn n một hai âm tiết — với câu ngắn thế
  đã quá 5 %. Trong app, câu vượt khung được vòng lặp ngân sách dịch lại với token nhỏ hơn (bộ gold:
  6/68 → 0/68 đơn vị đọc), nhưng tỉ lệ câu phải nén trong một lần lồng tiếng thật chưa đo.
- Ngoại lệ phải ghi: adapter Nhật dùng cho tiếng Anh làm chrF giảm 4,1 điểm (có ý nghĩa) — nó dịch
  quá ngắn (phải nén chỉ 15,5 % nhưng mất nghĩa).
- Giới hạn: n lấy từ bản tham chiếu chứ không từ khung giờ thật; một lần huấn luyện mỗi adapter;
  COMET chưa đo (cần tải mô hình ~2,3 GB). Bảng của lần đo trước với bản Trung 11/11:
  `data/_bench/nllb_lora_cross_v1_21-11.json`.

```bash
data/_train_venv/Scripts/python training/eval_nllb_lora.py          # bộ gold + bảng chéo (~35 phút trên RTX 4060)
data/_train_venv/Scripts/python training/bootstrap_cross.py         # khoảng tin cậy 95 % (CPU, ~40 giây)
```

### App dùng adapter thế nào

`backend/core/translate.py` nạp **mọi** adapter có trong `data/models` (có `adapter_config.json`)
lên cùng một NLLB, khi môi trường của app có `peft` (nhóm `offline`: `uv sync --extra offline`).
Mỗi lượt dịch bật đúng adapter của ngôn ngữ nguồn (`translate.lora_for`); ngôn ngữ chưa có
adapter, hoặc đích không phải tiếng Việt, thì tắt hết adapter và chạy NLLB gốc. Khi bật "vòng
lặp ngân sách" với engine NLLB, câu vượt khung được dịch lại với `<len:n>`; câu nào không ngắn
đi thì rơi về bộ luật HP-5. Tắt hẳn: `VSUB_NLLB_LORA=0`.

## Âm Hán Việt khi dịch Trung → Việt (21/11/2026)

Google và NLLB để tên riêng, xưng hô cổ trang ở dạng pinyin hoặc dịch sát chữ (bộ gold: 郎君 →
"Lang Jun", 霍 → "Huo", 春风楼 → "tháp Chunfeng", 奴家 → "gia đình nô lệ"; NLLB còn bịa tên:
"Roku", "Hồ Chí Minh"). `backend/core/hanviet.py` sửa việc đó mà không cần mạng hay mô hình:

1. **Từ điển âm Hán Việt** `backend/core/hanviet_data.tsv` (13.645 chữ, âm theo từng pinyin),
   dựng bằng `training/build_hanviet.py` từ `hanviet.csv` (Phong Phan, MIT — soạn theo Thiều
   Chửu, Trần Văn Chánh…) + Unihan (pinyin, giản ↔ phồn thể). Trường kVietnamese của Unihan
   đã thử và bỏ: thiếu 春 何 胡 劉, lẫn âm Nôm (朱 "cho").
2. **Bộ thuật ngữ tự học** `data/hanviet_learned.json`: cụm chữ Hán → cách viết Hán Việt, học từ
   chỗ người dùng sửa tay ở bước 4 (khi xuất), từ bộ thuật ngữ đã gõ ở mọi dự án, và tên riêng
   lặp lại trong bản dịch AI. Ưu tiên: sửa tay > thuật ngữ > AI. Lúc dịch bằng Google /
   MyMemory / NLLB, cụm đã học có mặt trong kịch bản được cài vào câu gốc như bộ thuật ngữ.
   `training/collect_hanviet.py` học bù từ các dự án làm trước khi có tính năng này.
3. **Sửa phiên âm sót** sau khi dịch (mọi engine): đoạn pinyin viết hoa ("Lang Jun", "Chunfeng")
   khớp được với các chữ trong câu gốc thì đổi sang âm Hán Việt của đúng các chữ đó. Từ tiếng
   Việt trùng mặt chữ pinyin (an, ba, lang…) không bị đụng tới.

Tắt hẳn: `VSUB_HANVIET=0`. Đo: `.venv/Scripts/python training/eval_hanviet.py` — học từ nửa đầu
bộ gold (người dùng sửa bản Google thành bản tham chiếu), chỉ đo trên nửa sau:

| Nửa sau bộ gold (136 câu) | BLEU | chrF | Cụm Hán Việt đúng | Phiên âm sót |
|---|---|---|---|---|
| Google | 7,8 | 29,5 | 6/50 = 12 % | 7 |
| Google + sửa phiên âm (chỉ từ điển) | 7,8 | 29,9 | 10/50 = 20 % | 0 |
| Google + cụm học ở nửa đầu | 8,3 | 30,3 | 12/50 = 24 % | 1 |
| Google + cụm đã học + sửa phiên âm | 8,3 | 30,5 | 12/50 = 24 % | 0 |
| *Mốc: Google + bộ thuật ngữ người dùng tự gõ cho cả video* | *10,9* | *32,8* | *24/50 = 48 %* | *0* |

Trên cả 271 câu, riêng bước sửa phiên âm đưa cụm Hán Việt đúng từ 11/99 lên 27/99 và hết 22 chỗ
pinyin sót. Khoảng cách tới bộ thuật ngữ tự gõ là vì người dùng soạn bộ đó cho cả video, còn
máy chỉ được học từ nửa đầu.

### Adapter Trung học thêm âm Hán Việt (21/11/2026) — bản đang dùng

`training/build_hanviet_corpus.py` tìm trong 13,5 triệu cặp OPUS vi–zh_CN những cặp có bản Việt đọc
tên riêng / xưng hô theo âm Hán Việt (`hanviet.harvest`; cụm viết hoa hoặc thuộc danh sách xưng hô
cổ trang): 244.441 cặp, lấy ngẫu nhiên 60.000. Một nửa (29.997 cặp) được **cài sẵn cụm Hán Việt vào
câu gốc** đúng như app làm với bộ thuật ngữ, để mô hình học giữ nguyên cụm đã cài thay vì dịch lại.
Gộp với 298.499 cặp cũ (bỏ 500 cặp dev cũ để còn so trên cùng tập; loại câu trùng / gần trùng bộ
gold), huấn luyện lại từ đầu: 357.471 cặp, 11.171 bước, 50 phút; loss dev 2,3214 → 2,1933.

```bash
data/_train_venv/Scripts/python -I -X utf8 training/build_hanviet_corpus.py data/_opus/dl/vi-zh_CN.txt.zip  # → data/corpus/vidub_train_hv.jsonl
data/_train_venv/Scripts/python training/train_nllb_lora.py --src zh --corpus data/corpus/vidub_train_hv.jsonl \
    --origins extra,hanviet --out data/models/nllb_lora_dangthoi_hv --dev 500
data/_train_venv/Scripts/python training/eval_nllb_lora.py --no-cross --zh-adapter data/models/nllb_lora_dangthoi_hv
data/_train_venv/Scripts/python training/eval_hanviet.py --nllb --no-google \
    --zh-adapter data/models/nllb_lora_dangthoi --zh-adapter data/models/nllb_lora_dangthoi_hv
```

| Phép đo | Bản 11/11 | Bản Hán Việt |
|---|---|---|
| Bộ gold 271 câu, không token: BLEU / chrF | 5,6 / 22,3 | **6,7 / 23,1** |
| Bộ gold, bộ siết của app: BLEU / chrF / đơn vị đọc vượt khung | 5,5 / 20,5 / 0/68 | **6,8 / 21,5** / 0/68 |
| Nửa sau bộ gold, cài cụm đã học + sửa phiên âm: cụm Hán Việt đúng | 6/50 = 12 % | **9/50 = 18 %** |
| … cùng cấu hình: BLEU / chrF | 6,2 / 24,0 | **7,8 / 25,6** |
| Tập dev Trung (465 câu) + `<len:n>`: ±1 âm tiết / phải nén / chrF | 81,5 % / 32,0 % / 30,8 | 83,0 % / 32,3 % / 31,1 |
| Dùng cho Pháp / Nga / Thái + `<len:n>`: ±1 âm tiết | 52,4 / 63,6 / 65,6 % | **64,2 / 73,6 / 74,2 %** |

Bộ gold, bootstrap ghép cặp 1.000 lượt: BLEU +1,07 [+0,16; +2,05] — có ý nghĩa; chrF +0,81
[−0,16; +1,70] — chưa đủ chắc. Cụm Hán Việt 9 so với 6 trên 50 cụm là quá ít để kết luận chắc.
So trên cùng tập (`data/_bench/nllb_lora_cross_zh_{v1,hv}.json`), kém đi rõ nhất ở hai chỗ: phải nén
trên tiếng Pháp 24,6 → 27,0 % (vẫn dưới 35 %) và BLEU khi dùng adapter Trung cho tiếng Nhật 9,6 → 8,8
(trong app không xảy ra vì tiếng Nhật có adapter riêng); vài ô khác lệch xuống không quá 0,3 điểm
(phải nén tập dev Trung 32,0 → 32,3 %, chrF tiếng Nhật, BLEU tiếng Thái). Các phép đo còn lại tốt
hơn, nhiều chỗ tốt hơn hẳn, nên bản Hán Việt thay bản 11/11 (cất ở
`data/models/_ban_cu/nllb_lora_dangthoi_v1_11-11`, bản dịch bộ gold ở `data/_bench/gold/v1_11-11/`).
Giới hạn: NLLB vẫn kém Google ở khoản này (Google + cụm đã học + sửa phiên âm: 12/50), và cả hai còn
xa bộ thuật ngữ người dùng tự gõ (24/50) — cụm Hán Việt chủ yếu vẫn nhờ bộ thuật ngữ tự học và
bước sửa phiên âm; adapter giúp giữ đúng cụm đã cài và dịch câu cổ trang khá hơn.

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
- `backend/core/hanviet.py` — âm Hán Việt: tìm cụm, bộ thuật ngữ tự học, sửa phiên âm sót

Nhờ vậy sửa notebook không làm hỏng app, và ngược lại mô hình huấn luyện xong
được app nạp thẳng qua `duration.default_model()`.

## Lưu ý khi commit

Xoá hết output trước khi commit (`Kernel → Restart & Clear Output`). Output làm
diff phình to và có thể lộ đường dẫn máy cá nhân. Có test canh việc này.
