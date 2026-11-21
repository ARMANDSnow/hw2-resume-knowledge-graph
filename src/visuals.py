"""Accessible static figures for the independent reports and the Streamlit demo."""
from pathlib import Path
import os
import tempfile

# Keep repeated command-line runs fast on hosts with a read-only home cache.
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "hw2-kg-matplotlib"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

COLORS = ("#0072B2", "#D55E00", "#009E73", "#CC79A7")
DIMENSIONS = ("EDU", "EXP", "SKL", "POT")
AXES = ("Education", "Experience", "Skills", "Potential")


def radar(scores_by_name, path, title=""):
    """Plot one or more candidates on the same 0–100 scale."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    angle = np.linspace(0, 2 * np.pi, len(AXES), endpoint=False)
    closed = np.append(angle, angle[0])
    fig, ax = plt.subplots(figsize=(6.3, 5.4), subplot_kw={"projection": "polar"})
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_xticks(angle, AXES, fontsize=10)
    ax.tick_params(axis="x", pad=10)
    ax.set_ylim(0, 100)
    ax.set_yticks([25, 50, 75, 100])
    ax.set_yticklabels(["25", "50", "75", "100"], fontsize=8, color="#475569")
    for idx, (name, scores) in enumerate(scores_by_name.items()):
        values = [scores[k] for k in DIMENSIONS]
        values.append(values[0])
        color = COLORS[idx % len(COLORS)]
        ax.plot(closed, values, label=name, color=color, linewidth=2,
                marker=("o", "s", "^", "D")[idx % 4], linestyle=("-", "--", "-.", ":")[idx % 4])
        ax.fill(closed, values, color=color, alpha=0.07)
    ax.grid(color="#CBD5E1")
    ax.spines["polar"].set_color("#94A3B8")
    if title:
        fig.suptitle(title)
    fig.legend(loc="lower center", frameon=False, ncol=1 if len(scores_by_name) > 1 else 2)
    fig.subplots_adjust(top=.84, bottom=.22)
    fig.savefig(path, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def entity_distribution(stats, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    kinds = list(stats["all"]["nodes"])
    y = np.arange(len(kinds))
    fig, ax = plt.subplots(figsize=(8, max(4, len(kinds) * .62)))
    for i, scope in enumerate(("train", "test", "all")):
        values = [stats[scope]["nodes"].get(k, 0) for k in kinds]
        ax.barh(y+(i-1)*.24, values, .23, color=COLORS[i], label=scope)
    ax.set_yticks(y, kinds)
    ax.invert_yaxis()
    ax.set_xlabel("Distinct reachable nodes")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
