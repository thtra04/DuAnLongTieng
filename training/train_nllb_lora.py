"""HP-4 — huấn luyện LoRA cho NLLB-200 distilled 600M dịch X→vi có token ngân sách `<len:n>`.

    python training/train_nllb_lora.py                 # Trung → Việt; chạy / chạy tiếp từ checkpoint gần nhất
    python training/train_nllb_lora.py --max-minutes 100
    python training/train_nllb_lora.py --src ko        # Hàn → Việt, đọc data/corpus/opus_ko_vi.jsonl (cũng: ja, en)

Mỗi ngôn ngữ nguồn một adapter riêng (`isochron.adapter_dir(MODEL_DIR, lang)`): Trung → Việt
ở `nllb_lora_dangthoi`, các thứ tiếng khác thêm hậu tố `_ko`, `_ja`, `_en`.

Chạy bằng môi trường huấn luyện riêng (torch CUDA + transformers + peft + datasets),
KHÔNG phải `.venv` của app — xem training/README.md.

Cấu hình theo notebook 03: LoRA r=16, alpha=32 trên q_proj/v_proj, fp16. Khác notebook
ở ba chỗ, đều vì chạy thật mới lộ ra:

  * 60 token `<len:n>` là hàng embedding MỚI. LoRA trên q/v không đụng tới embedding,
    nên nếu chỉ `add_tokens` thì chúng mãi là véc-tơ ngẫu nhiên. Ở đây chỉ riêng 60
    hàng đó được huấn luyện (`trainable_token_indices` của PEFT) và lưu kèm adapter.
  * ~15 % mẫu KHÔNG gắn token, để adapter vẫn dịch tốt khi app gọi không kèm ngân sách.
  * Dừng êm sau `--max-minutes` và lưu checkpoint; chạy lại lệnh cũ là tiếp tục.

Kết quả: adapter + tokenizer + `train_meta.json` trong data/models/nllb_lora_dangthoi.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core import isochron  # noqa: E402

BASE_MODEL = "facebook/nllb-200-distilled-600M"
LORA = dict(r=16, lora_alpha=32, lora_dropout=0.05, target_modules=["q_proj", "v_proj"], task_type="SEQ_2_SEQ_LM")
_HAN = re.compile(r"[一-鿿]")


def load_pairs(path: Path, origins: set[str] | None, limit: int, seed: int, lang: str = "zh") -> list[dict]:
    rows = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        if origins and r.get("origin", "extra") not in origins:
            continue
        if (r.get("tgt_lang") or "vi") != "vi" or (r.get("src_lang") or "zh") != lang:
            continue
        if lang == "zh" and not _HAN.search(r["src"]):
            continue
        pair = {"src": r["src"], "tgt": r["tgt"]}
        if lang == "vi" and "cap" in r:
            if type(r["cap"]) is not int or not 1 <= r["cap"] <= isochron.BUDGET_MAX:
                raise ValueError("Spoken training cap must be an integer from 1 to 60.")
            pair["cap"] = r["cap"]
        rows.append(pair)
    random.Random(seed).shuffle(rows)
    return rows[:limit] if limit else rows


def build_examples(pairs: list[dict], no_budget_rate: float, seed: int) -> list[dict]:
    rng = random.Random(seed + 1)
    examples = []
    for p in pairs:
        keep = rng.random() >= no_budget_rate
        if keep and "cap" in p:
            # A reviewed cue can have a real timing budget, independent of reference length.
            examples.append({"src": isochron.with_budget(p["src"], p["cap"]), "tgt": p["tgt"]})
        else:
            examples.append(isochron.to_example(p["src"], p["tgt"], keep_budget=keep))
    return examples


def load_base(model_dir: Path, tok):
    """NLLB gốc đã nới embedding cho 60 token ngân sách (khởi tạo = trung bình embedding cũ)."""
    import torch
    from transformers import AutoModelForSeq2SeqLM

    model = AutoModelForSeq2SeqLM.from_pretrained(BASE_MODEL, cache_dir=str(model_dir))
    old = model.get_input_embeddings().weight.shape[0]
    if len(tok) > old:
        model.resize_token_embeddings(len(tok), mean_resizing=False)
        with torch.no_grad():
            w = model.get_input_embeddings().weight
            w[old:] = w[:old].mean(dim=0, keepdim=True)
    return model


def default_corpus(data_dir: Path, lang: str) -> Path:
    """Trung → Việt dùng corpus đã gộp và loại câu trùng bộ gold (build_corpus.py); thứ tiếng khác
    chưa có tập kiểm thử riêng nên đọc thẳng tệp đã lọc của prepare_opus.py."""
    return data_dir / "corpus" / ("vidub_train.jsonl" if lang == "zh" else f"opus_{lang}_vi.jsonl")


def load_tokenizer(model_dir: Path, src_lang: str = "zho_Hans", tgt_lang: str = "vie_Latn"):
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(BASE_MODEL, cache_dir=str(model_dir), src_lang=src_lang, tgt_lang=tgt_lang)
    tok.add_tokens(isochron.all_budget_tokens())
    return tok


def main() -> None:
    from backend.config import DATA_DIR, MODEL_DIR

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--task", choices=("isochron", "meaning", "spoken"), default="isochron",
                    help="meaning: X -> vi without a length token; spoken: vi -> spoken vi with a budget")
    ap.add_argument("--init-adapter", type=Path, help="Initialize trainable weights from a local adapter (not modified)")
    ap.add_argument("--src", choices=isochron.LANGS, default="zh", help="ngôn ngữ nguồn (đích luôn là tiếng Việt)")
    ap.add_argument("--corpus", type=Path, help="mặc định: Trung = vidub_train.jsonl, khác = opus_<src>_vi.jsonl")
    ap.add_argument("--out", type=Path, help="mặc định isochron.adapter_dir(MODEL_DIR, src)")
    ap.add_argument("--origins",
                    help="nguồn được dùng (mặc định bỏ 'ai': dự án cũ có thể cùng phim với tập kiểm thử)")
    ap.add_argument("--limit", type=int, default=0, help="chỉ lấy N cặp đầu sau khi xáo (0 = tất cả)")
    ap.add_argument("--dev", type=int, default=1000, help="số cặp tách riêng để theo dõi loss")
    ap.add_argument("--dev-corpus", type=Path, help="External dev JSONL from different films; do not split the train file")
    ap.add_argument("--select-best", action="store_true", help="Evaluate every epoch and restore the lowest dev-loss checkpoint")
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--accum", type=int, default=2)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--max-length", type=int, default=64)
    ap.add_argument("--no-budget-rate", type=float, default=0.15)
    ap.add_argument("--save-steps", type=int, default=1000)
    ap.add_argument("--max-steps", type=int, default=-1, help="dừng hẳn sau N bước (thử nhanh)")
    ap.add_argument("--max-minutes", type=float, default=100, help="dừng êm và lưu checkpoint sau ngần này phút")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--fresh", action="store_true", help="bỏ qua checkpoint cũ, huấn luyện lại từ đầu")
    args = ap.parse_args()
    if args.select_best and (not args.dev_corpus or args.task == "isochron"):
        ap.error("--select-best requires a separate task and a film-held-out --dev-corpus.")
    if args.task != "isochron":
        if not args.corpus or not args.out or (args.out.exists() and any(args.out.iterdir())):
            ap.error("Separate tasks require an explicit prepared corpus and a new/empty output directory.")
        args.no_budget_rate = float(args.task == "meaning")
    if args.init_adapter and not (args.init_adapter / "adapter_model.safetensors").is_file():
        ap.error("--init-adapter must be a local PEFT adapter with safetensors weights.")
    args.corpus = args.corpus or default_corpus(DATA_DIR, args.src)
    args.out = args.out or isochron.adapter_dir(MODEL_DIR, args.src)

    import torch
    from datasets import Dataset
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import (DataCollatorForSeq2Seq, Seq2SeqTrainer, Seq2SeqTrainingArguments,
                              TrainerCallback)

    if not torch.cuda.is_available():
        print("⚠ Không thấy GPU CUDA — huấn luyện trên CPU sẽ mất nhiều ngày.")
    else:
        print("GPU:", torch.cuda.get_device_name(0))

    default_origins = {"isochron": "extra,user", "meaning": "opus,reviewed",
                       "spoken": "parallel-variant,expanded,keep,reviewed"}
    origins = {o.strip() for o in (args.origins or default_origins[args.task]).split(",") if o.strip()}
    src = "vi" if args.task == "spoken" else args.src
    pairs = load_pairs(args.corpus, origins, args.limit, args.seed, src)
    if args.dev_corpus:
        from training.prepare_dialogue import terms

        train_pairs = pairs
        dev_pairs = load_pairs(args.dev_corpus, origins, 0, args.seed, src)
        dev_keys = set().union(*(terms(r) for r in dev_pairs))
        if not train_pairs or not dev_pairs or any(terms(r) & dev_keys for r in train_pairs):
            ap.error("Train and dev must be nonempty and disjoint on both source and target.")
    else:
        if args.dev < 1 or len(pairs) <= args.dev * 2:
            sys.exit(f"Corpus chỉ có {len(pairs)} cặp — cần tập train và dev riêng.")
        dev_pairs, train_pairs = pairs[: args.dev], pairs[args.dev:]
    print(f"{args.task} {src} → vi: {len(train_pairs):,} cặp huấn luyện, {len(dev_pairs):,} cặp dev từ {args.corpus}")

    tok = load_tokenizer(MODEL_DIR, src_lang="vie_Latn" if src == "vi" else isochron.NLLB_SRC[src])
    new_ids = tok.convert_tokens_to_ids(isochron.all_budget_tokens())
    base = load_base(MODEL_DIR, tok)
    if torch.cuda.is_available():
        # Mô hình gốc đóng băng nên giữ ở half precision: bớt ~1,2 GB VRAM. Đo thật trên
        # RTX 4060 8 GB: để fp32 thì batch 16 chạm trần, Windows tràn sang RAM dùng chung
        # và tốc độ rơi từ ~75 xuống ~35 mẫu/giây.
        base = base.half()
    model = (PeftModel.from_pretrained(base, str(args.init_adapter), is_trainable=True)
             if args.init_adapter else get_peft_model(base, LoraConfig(**LORA, trainable_token_indices=new_ids)))
    for p in model.parameters():
        if p.requires_grad:
            p.data = p.data.float()  # phần được huấn luyện phải là fp32 thì GradScaler mới chạy
    model.print_trainable_parameters()

    def encode(batch):
        return tok(batch["src"], text_target=batch["tgt"], truncation=True, max_length=args.max_length)

    def dataset(rows, rate, seed):
        ds = Dataset.from_list(build_examples(rows, rate, seed))
        return ds.map(encode, batched=True, remove_columns=["src", "tgt"], desc="token hoá")

    train_ds = dataset(train_pairs, args.no_budget_rate, args.seed)
    dev_ds = dataset(dev_pairs, args.no_budget_rate, args.seed + 7)

    started = time.monotonic()

    class TimeLimit(TrainerCallback):
        hit = False

        def on_step_end(self, a, state, control, **kw):
            if (time.monotonic() - started) / 60 >= args.max_minutes:
                TimeLimit.hit = True
                control.should_save = True
                control.should_training_stop = True

    ckpt_dir = args.out / "checkpoints"
    has_ckpt = any(ckpt_dir.glob("checkpoint-*")) and not args.fresh
    targs = Seq2SeqTrainingArguments(
        output_dir=str(ckpt_dir), learning_rate=args.lr, num_train_epochs=args.epochs, max_steps=args.max_steps,
        per_device_train_batch_size=args.batch, per_device_eval_batch_size=args.batch,
        gradient_accumulation_steps=args.accum, warmup_ratio=0.03, lr_scheduler_type="linear",
        fp16=torch.cuda.is_available(), logging_steps=50, save_steps=args.save_steps,
        save_strategy="epoch" if args.select_best else "steps", eval_strategy="epoch" if args.select_best else "steps",
        load_best_model_at_end=args.select_best, metric_for_best_model="eval_loss" if args.select_best else None,
        eval_steps=args.save_steps, save_total_limit=2, report_to=[],
        group_by_length=True, dataloader_num_workers=0, seed=args.seed, label_names=["labels"],
    )
    trainer = Seq2SeqTrainer(model=model, args=targs, train_dataset=train_ds, eval_dataset=dev_ds,
                             data_collator=DataCollatorForSeq2Seq(tok, model=model, pad_to_multiple_of=8),
                             callbacks=[TimeLimit()])
    if has_ckpt:
        print("Chạy tiếp từ checkpoint gần nhất trong", ckpt_dir)
    result = trainer.train(resume_from_checkpoint=has_ckpt)

    done = not TimeLimit.hit
    model.save_pretrained(args.out)
    tok.save_pretrained(args.out)
    evals = [h for h in trainer.state.log_history if "eval_loss" in h]
    meta = {
        "base_model": BASE_MODEL, "task": args.task, "src_lang": src, "seed": args.seed,
        "init_adapter": args.init_adapter.name if args.init_adapter else None,
        "corpus_sha256": hashlib.sha256(args.corpus.read_bytes()).hexdigest(),
        "lora": {k: v for k, v in LORA.items()},
        "budget_tokens": isochron.BUDGET_MAX,
        "corpus": str(args.corpus.name), "origins": sorted(origins), "train_pairs": len(train_pairs),
        "dev_corpus": args.dev_corpus.name if args.dev_corpus else None,
        "selected_checkpoint": Path(trainer.state.best_model_checkpoint).name if args.select_best and trainer.state.best_model_checkpoint else None,
        "dev_pairs": len(dev_pairs), "epochs": args.epochs, "batch": args.batch * args.accum, "lr": args.lr,
        "no_budget_rate": args.no_budget_rate, "global_step": trainer.state.global_step,
        "max_steps": trainer.state.max_steps, "finished": done,
        "train_loss": round(float(result.training_loss), 4),
        "eval_loss": [(h["step"], round(h["eval_loss"], 4)) for h in evals],
    }
    (args.out / "train_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Bước {trainer.state.global_step}/{trainer.state.max_steps}; adapter -> {args.out}")
    if not done:
        print("⏸ Hết thời gian cho phép — chạy lại đúng lệnh này để huấn luyện tiếp.")
        sys.exit(3)
    print("✓ Huấn luyện xong.")


if __name__ == "__main__":
    main()
