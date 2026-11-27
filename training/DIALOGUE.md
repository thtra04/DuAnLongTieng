# Dịch phụ đề và soạn lời đọc

Hai adapter LoRA dùng chung NLLB-200 distilled 600M, không cần giữ hai bản model gốc trong VRAM:

| Adapter | Đầu vào → đầu ra | Dùng ở đâu |
|---|---|---|
| `meaning_zh` | Câu Trung → câu Việt, không kèm mục tiêu độ dài | Engine **NLLB offline**, khi dịch phụ đề thông thường |
| `spoken_vi` | Câu Việt đã duyệt + `<len:n>` → câu Việt dễ đọc trong khoảng `n` âm tiết | **Rút gọn câu đọc không kịp** lúc dựng kịch bản / xuất tiếng Việt, kể cả phụ đề đã dịch bằng engine khác |

Câu nào đã vừa thì không cần viết lại. Nếu luật đã rút gọn đủ thì cũng không gọi model.
Model chỉ được dùng trên phần lời còn dài; ứng viên rơi mất phủ định, đổi số/đơn vị, xưng hô
được nhận diện, hoặc quá khác bản đã duyệt thì bị bỏ. Đây là bộ lọc thận trọng, **không phải
bộ kiểm chứng ngữ nghĩa**. Nghe và duyệt riêng kịch bản; chấp nhận câu còn dài thay vì cắt ý.
VieNeu-TTS vẫn phụ trách âm thanh. Không lấy audio từ dự án, nhân bản giọng hay huấn luyện model âm học.

## Notebook huấn luyện tiếp

Mở [05_dich_va_loi_doc.ipynb](05_dich_va_loi_doc.ipynb) bằng Jupyter. **Run All** mặc định chỉ
xem báo cáo cục bộ. Để train tiếp, trỏ `REVIEWED` tới JSONL có `film`, `src_lang`, `tgt_lang`,
`src`, `tgt`, `spoken`, `cap`; có thể kèm `checks` chứa các nhóm từ đồng nghĩa cần giữ.
Notebook tách nguyên phim vào train/dev/test, lọc câu trùng cả hai phía, huấn luyện riêng từng
tác vụ, lấy checkpoint có loss thấp nhất trên **dev**, rồi hiển thị cả những câu dự đoán xấu đi.
Adapter lời đọc học theo `cap` của khung thoại nếu người duyệt cung cấp, không dùng độ dài
đáp án làm đầu vào để chấm điểm. Nên giữ cả các câu không thể rút thêm mà không mất ý.
Đổi `RUN` để không ghi đè; sau khi duyệt dev, đặt `DO_TRAIN=False`, `FINAL_TEST=True` để chấm test.
Ô **Đọc kết quả qua ba biểu đồ** cần `matplotlib` trong kernel Jupyter (không cần GPU):
so chrF theo tập, ngân sách/lỗi của bốn cách viết lời đọc và loss theo các bước đã ghi.
Biểu đồ loss lấy từ checkpoint cùng lượt; nếu chỉ còn số đo dev, notebook chỉ vẽ các điểm dev đó.

## Kết quả thí điểm trên máy

Hai adapter trong `data/models/dialogue_lab_v1/` đều khởi tạo từ adapter Trung đang dùng; mỗi
adapter học 6.016 cặp, 128 cặp dev, 376 bước trên RTX 4060 Laptop 8 GB. Lượt này không có dữ
liệu người dùng duyệt mới: 6.144 cặp MT lấy từ OPUS; tập lời đọc gồm 348 biến thể phụ đề gióng
cùng câu nguồn, 4.457 đầu vào kéo dài nhân tạo và 1.339 câu cần giữ nguyên. Không nên lấy loss
thấp trên nhãn tổng hợp làm bằng chứng giọng đọc tự nhiên hơn.

| Đo ngoài dữ liệu train | Mốc so sánh | Sau khi train |
|---|---:|---:|
| Dịch: chrF trên 32 câu thoại tự soạn | 38,10 | 38,35 |
| Dịch: nhóm từ kiểm tra khớp trên 8 câu trong số đó | 15/20 | 16/20 |
| Dịch: chrF trên 192 cặp OPUS khác, lọc trùng cả hai phía với các corpus đã chỉ định | 29,62 | 29,28 |
| Lời đọc: câu vừa ngân sách trên 32 câu (luật → luật + model có bộ lọc) | 3/32 | 3/32 |
| Lời đọc: chrF với kịch bản tham chiếu (cùng hai cấu hình) | 77,19 | 77,45 |

Ví dụ: model dịch mới lấy lại ý *vé là của dì* mà bản cũ đã bỏ; nhưng tên 小林 lại ra *Jung*,
vẫn sai. Model lời đọc thô chỉ có **1/32** câu đạt ngân sách và có **2** câu lệch dấu hiệu
cần giữ; sau lọc không còn lệch dấu hiệu đã kiểm tra, không có nghĩa là mọi câu đều đúng.
Một lần đọc thử bằng cùng giọng VieNeu-TTS Minh Đức cho 3,12 s → 2,80 s ở câu
“Tôi cứ tưởng rằng anh đang nói về tối ngày hôm qua.” Đây là một bản WAV minh họa, không phải
đo cảm nhận người nghe. File đối chiếu từng câu: `data/models/dialogue_lab_v1/eval.json`;
hai WAV ở `data/_bench/dialogue_audition_v1/`. **Chưa đủ căn cứ bật model mới mặc định.**

## Dữ liệu nào được dùng?

Chỉ định tệp OPUS OpenSubtitles đã tải về máy. Script mới không đọc `jobs/`, video, bộ nhớ dịch hay
API. Bản dịch máy, bản sửa tự động không mặc nhiên trở thành nhãn. Hai kiểu phụ đề cùng gióng với
một câu nguồn, có độ trùng từ cao, là **nhãn yếu**, không phải câu đã được diễn viên xác nhận.
Để bổ sung dữ liệu, có thể dùng `--reviewed duyet.jsonl` (hoặc chỉ dùng tệp này, bỏ `--opus`):
mỗi dòng là một câu **đã duyệt cho phép huấn luyện**, ví dụ:

```json
{"src_lang":"zh","tgt_lang":"vi","src":"别急着换车票。","tgt":"Đừng vội đổi vé xe nhé.","spoken":"Đừng vội đổi vé xe."}
```

`tgt` dạy model dịch; `spoken` (không bắt buộc) dạy model viết lời đọc từ `tgt`. Khi trùng
đầu vào, dữ liệu duyệt được ưu tiên. Tách tập kiểm tra thành các cảnh/tập phim khác **trước** khi
chọn nhãn train. Tệp kiểm tra cần thêm `cap` (ngân sách âm tiết của người biên tập); script
loại trùng sau chuẩn hóa ở cả lời gốc, bản dịch và lời đọc. Lọc trùng câu không đảm bảo tách
được phim nếu corpus không có mã phim. Tôn trọng giấy phép dữ liệu, model và quyền của người đọc;
NLLB-200 distilled 600M mang giấy phép CC-BY-NC-4.0, không mặc nhiên dùng cho thương mại.

## Huấn luyện và đo lại

Chạy từ gốc repo bằng môi trường huấn luyện riêng trong [README.md](README.md). Ví dụ **Git Bash
trên Windows**, với cache OPUS, NLLB và adapter Trung hiện hành đã có trên máy. Mỗi lượt chọn thư
mục đích mới; script không thay model đang dùng. Hai lệnh train chạy **lần lượt** trên một GPU.

```bash
PY=data/_train_venv/Scripts/python.exe
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUTF8=1
BASE=data/models/nllb_lora_dangthoi
RUN=data/models/dialogue_trial_02
CORP=data/corpus/dialogue_trial_02
ZIP=data/_opus/dl/vi-zh_CN.txt.zip
TEST=training/dialogue_holdout.jsonl
"$PY" -m training.prepare_dialogue --opus "$ZIP" --holdout "$TEST" --out "$CORP" --scan 240000 --limit 6144
"$PY" training/train_nllb_lora.py --task meaning --corpus "$CORP/meaning.jsonl" --init-adapter "$BASE" \
  --out "$RUN/meaning_zh" --seed 42 --dev 128 --batch 8 --accum 2 --lr 0.00005 --save-steps 320
"$PY" training/train_nllb_lora.py --task spoken --corpus "$CORP/spoken.jsonl" --init-adapter "$BASE" \
  --out "$RUN/spoken_vi" --seed 42 --dev 128 --batch 8 --accum 2 --lr 0.00015 --save-steps 320
"$PY" -m training.eval_dialogue --meaning "$RUN/meaning_zh" --spoken "$RUN/spoken_vi" \
  --holdout "$TEST" --opus "$ZIP" --exclude data/corpus/vidub_train_hv.jsonl \
  --exclude "$CORP/meaning.jsonl" --exclude "$CORP/spoken.jsonl" --out "$RUN/eval.json"
```

Để đánh giá trên corpus khác, truyền đúng các tệp `--exclude` của cả model xuất phát và lượt
train mới. Không so loss trên các bộ dev khác nhau để kết luận chất lượng. Đánh giá lời đọc
nhận cùng một bản dịch đã duyệt ở mọi cột; như vậy lỗi dịch không bị tính nhầm thành lỗi lồng tiếng.
`fits` đếm câu đạt ngân sách âm tiết, **không phải** số lần đọc vừa khung hình.

## Thử trong studio

Mặc định vẫn dùng các model đã cài trước. Trên **PowerShell** có thể bật riêng một hoặc cả hai
adapter đã train trên máy này rồi khởi động lại app:

```powershell
$env:VSUB_MEANING_ADAPTER = (Resolve-Path 'data/models/dialogue_lab_v1/meaning_zh').Path
$env:VSUB_SPOKEN_ADAPTER = (Resolve-Path 'data/models/dialogue_lab_v1/spoken_vi').Path
uv run python run.py
```

Chọn nguồn **Tiếng Trung**, đích **Tiếng Việt**, engine **NLLB offline**, tắt rút gọn ở bước 2 để
đánh giá riêng model dịch. Để thử lời đọc, bật rút gọn khi xuất và chọn **Dựng kịch bản**. Gỡ
biến môi trường tương ứng rồi khởi động lại để quay về model dịch trước đó / rút lời bằng luật.
Model khác ngôn ngữ, chưa train xong hoặc không được chủ máy chọn sẽ không tự kích hoạt.
Nếu dùng notebook, thay hai đường dẫn ví dụ bằng `meaning_zh` và `spoken_vi` trong `RUN` đã duyệt.
