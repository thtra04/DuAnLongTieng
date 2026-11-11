# training/ — phần huấn luyện AI

Bốn notebook, chạy theo thứ tự số. Mỗi notebook tự tìm gốc dự án nên mở từ thư
mục nào cũng chạy được.

| Notebook | Hợp phần | Việc | Cần gì |
|---|---|---|---|
| `01_sinh_du_lieu_thoi_luong.ipynb` | HP-3 | Cho VieNeu-TTS đọc từng câu, đo số giây → `data/duration/samples.csv` | Nhóm `tts` |
| `02_huan_luyen_duration.ipynb` | HP-3 | Huấn luyện mô hình dự đoán thời lượng đọc, so với ước lượng thô | Không |
| `03_lora_nllb_dang_thoi.ipynb` | HP-4 | LoRA cho NLLB-200 dịch ràng buộc độ dài | GPU + corpus, **chưa chạy** |
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

Dưới ~5.000 cặp thì chưa đủ cho LoRA; script tự cảnh báo.

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

Nhờ vậy sửa notebook không làm hỏng app, và ngược lại mô hình huấn luyện xong
được app nạp thẳng qua `duration.default_model()`.

## Lưu ý khi commit

Xoá hết output trước khi commit (`Kernel → Restart & Clear Output`). Output làm
diff phình to và có thể lộ đường dẫn máy cá nhân. Có test canh việc này.
