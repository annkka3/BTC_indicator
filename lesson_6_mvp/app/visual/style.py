# app/visual/style.py
import matplotlib as mpl
def apply_light():
    mpl.rcParams.update({
        "figure.dpi": 160,
        "savefig.bbox": "tight",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": "#C8D0D9",
        "grid.alpha": 0.35,
        "grid.linewidth": 0.6,
        "axes.facecolor": "white",
        "figure.facecolor": "white",
        "font.size": 9,
        "axes.labelsize": 9,
        "axes.titlesize": 11,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
    })
