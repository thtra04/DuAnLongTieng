"""Figures for notebook 05; only reads evaluation results and local trainer logs."""
import json

import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator


INK, TEAL, COPPER, PAPER = "#263b3c", "#14766e", "#a35130", "#fbf8f0"
STYLE = {"figure.facecolor": PAPER, "axes.facecolor": PAPER, "axes.edgecolor": "#ccc6b9",
         "axes.spines.right": False, "axes.spines.top": False, "font.family": "DejaVu Sans",
         "text.color": INK, "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK,
         "figure.dpi": 125, "legend.frameon": False, "axes.axisbelow": True}


def heading(fig, title):
    fig.suptitle(title, fontfamily="DejaVu Serif", fontsize=16)


def translation(report):
    with plt.rc_context(STYLE):
        fig, (ax, delta) = plt.subplots(1, 2, figsize=(9, 3.8), width_ratios=(1.8, 1), layout="constrained")
        heading(fig, "01  /  Bản dịch gần tham chiếu đến đâu?")
        mt = report["mt"]
        keys = list(mt["current"])
        names = {"dialogue": "Hội thoại", "parallel": "OPUS"}
        labels = [f"{names.get(k, k)}\n{mt['current'][k]['n']} câu" for k in keys]
        for variant, offset, color, label in (("current", -.17, "#758784", "Hiện hành"),
                                              ("candidate", .17, TEAL, "Sau huấn luyện")):
            vals = [mt[variant][k]["chrf"] for k in keys]
            bars = ax.barh([i + offset for i in range(len(keys))], vals, .29, color=color, label=label)
            ax.bar_label(bars, fmt="%.2f", padding=4)
        ax.set_yticks(range(len(keys)), labels)
        ax.invert_yaxis()
        ax.margins(x=.20, y=.25)
        ax.set_xlabel("chrF · cao hơn là gần tham chiếu hơn")
        ax.legend(loc="lower center", bbox_to_anchor=(.5, 1), ncol=2, fontsize=9)
        changes = [mt["candidate"][k]["chrf"] - mt["current"][k]["chrf"] for k in keys]
        span = max(.1, *map(abs, changes)) * 1.65
        delta.axvline(0, color=INK, lw=1)
        for i, d in enumerate(changes):
            color = TEAL if d >= 0 else COPPER
            delta.hlines(i, 0, d, color=color, lw=3)
            delta.scatter(d, i, color=color, zorder=3)
            delta.annotate(f"{d:+.2f}", (d, i), xytext=(0, 10), textcoords="offset points", ha="center")
        delta.set(xlim=(-span, span), ylim=ax.get_ylim(), yticks=[], xlabel="Chênh lệch chrF (mới − cũ)")
        for panel in (ax, delta):
            panel.grid(axis="x", alpha=.18)
        return fig


def spoken(report):
    with plt.rc_context(STYLE):
        fig, axes = plt.subplots(1, 3, figsize=(10, 3.5), sharey=True, layout="constrained")
        heading(fig, "02  /  Rút lời đọc: vừa khung hay mất ý?")
        scores = report["spoken"]
        names = {"unchanged": "Giữ nguyên", "rules": "Chỉ dùng luật", "model_raw": "Model thô",
                 "rules_plus_model": "Luật + model có lọc"}
        labels = [names.get(k, k) for k in scores]
        for ax, metric, title, color in zip(axes, ("chrf", "fits", "anchor_mismatch"),
                                             ("chrF với lời duyệt", "Vừa ngân sách âm tiết", "Lệch dấu hiệu cần giữ"),
                                             ("#758784", TEAL, COPPER)):
            vals = [s[metric] for s in scores.values()]
            bars = ax.barh(range(len(vals)), vals, height=.54, color=color)
            tags = [f"{v:.2f}" if metric == "chrf" else f"{v}/{s['n']}" for v, s in zip(vals, scores.values())]
            ax.bar_label(bars, labels=tags, padding=4, fontsize=10)
            ax.set_xlim(0, 100 if metric == "chrf" else max(1, max(vals)) * 1.55)
            ax.set_title(title, fontsize=11)
            ax.set_xlabel("Điểm" if metric == "chrf" else "Số câu")
            ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=4))
            ax.grid(axis="x", alpha=.18)
        axes[0].set_yticks(range(len(labels)), labels)
        axes[0].invert_yaxis()
        return fig


def history(folder):
    # The most recent checkpoint contains cumulative history; don't double-count older checkpoints.
    states = [p for p in folder.glob("checkpoints/checkpoint-*/trainer_state.json")
              if p.parent.name.split("-")[-1].isdigit()]
    rows = []
    if states:
        latest = max(states, key=lambda p: int(p.parent.name.split("-")[-1]))
        rows = json.loads(latest.read_text(encoding="utf-8"))["log_history"]
    train = [(r["step"], r["loss"]) for r in rows if "step" in r and "loss" in r]
    dev = [(r["step"], r["eval_loss"]) for r in rows if "step" in r and "eval_loss" in r]
    meta = folder / "train_meta.json"
    if not dev and meta.is_file():
        dev = json.loads(meta.read_text(encoding="utf-8")).get("eval_loss", [])
    return train, dev


def losses(run_dir, lang):
    traces = [history(run_dir / key) for key in ("meaning_" + lang, "spoken_vi")]
    if not any(train or dev for train, dev in traces):
        return None
    with plt.rc_context(STYLE):
        fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.8), layout="constrained")
        heading(fig, "03  /  Hai tác vụ học như thế nào?")
        for ax, (train, dev), task in zip(axes, traces, ("Dịch phụ đề", "Viết lời đọc")):
            if train:
                ax.plot(*zip(*train), marker="o", ms=4, lw=1.8, color=TEAL, label="Train")
            if dev:
                ax.scatter(*zip(*dev), marker="D", color=COPPER, label="Dev", zorder=3)
                x, y = dev[-1]
                ax.annotate(f"{y:.3f}", (x, y), xytext=(0, 10), textcoords="offset points", ha="center")
            if train or dev:
                ax.legend()
            else:
                ax.text(.5, .5, "Không có log", ha="center", transform=ax.transAxes)
            ax.grid(alpha=.18)
            ax.margins(x=.12, y=.20)
            ax.set(title=task, xlabel="Bước tối ưu", ylabel="Loss")
        return fig
