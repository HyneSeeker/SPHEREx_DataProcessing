from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from .horizons import max_sot_peak_hours
from .timeutils import datetime_to_ut_hour
from .types import HorizonsRecord, ObservationResult


def plot_day(
    observations: list[ObservationResult],
    horizons: list[HorizonsRecord],
    *,
    observing_date,
    output_path: Path,
) -> None:
    if not observations:
        raise ValueError("No valid observations to plot")

    ordered = sorted(observations, key=lambda item: item.time)
    fig, ax1 = plt.subplots(figsize=(12, 4))
    ax1.plot(
        [datetime_to_ut_hour(item.time, observing_date) for item in ordered],
        [item.intensity_rayleigh for item in ordered],
        color="black",
        linestyle="-.",
        linewidth=1.5,
        label="Intensity",
        zorder=1,
    )

    style_by_label = {
        "South": {
            "marker": "*",
            "edgecolors": "blue",
            "facecolors": "none",
            "label": r"Orbit sub-lat $< -80^{\circ}$",
            "s": 70,
        },
        "North": {
            "marker": "o",
            "edgecolors": "red",
            "facecolors": "none",
            "label": r"Orbit sub-lat $> +80^{\circ}$",
            "s": 55,
        },
    }
    for label in ("North", "South"):
        label_data = [item for item in ordered if item.label == label]
        if not label_data:
            continue
        style = style_by_label[label]
        ax1.scatter(
            [datetime_to_ut_hour(item.time, observing_date) for item in label_data],
            [item.intensity_rayleigh for item in label_data],
            s=style["s"],
            marker=style["marker"],
            facecolors=style["facecolors"],
            edgecolors=style["edgecolors"],
            linewidth=1.0,
            label=style["label"],
            zorder=3,
        )

    _plot_sot_peaks(ax1, horizons, observing_date)

    ax1.set_xlabel("UT time (h)", fontsize=16)
    ax1.set_ylabel(r"He I (Rayleigh)", color="black", fontsize=16)
    ax1.tick_params(axis="y", labelcolor="black")
    ax1.set_title(f"UT {observing_date.isoformat()}", fontsize=18, fontweight="bold")
    ax1.set_xlim(0, 24)
    ax1.set_xticks(np.arange(0, 25, 1))
    ax1.set_xticks(np.arange(0, 24.5, 0.5), minor=True)
    max_intensity = max(item.intensity_rayleigh for item in ordered)
    ax1.set_ylim(0, max_intensity * 1.12 if max_intensity > 0 else 1)
    ax1.tick_params(
        axis="both",
        which="major",
        direction="in",
        top=True,
        right=True,
        length=8,
        width=1.6,
        labelsize=13,
    )
    ax1.tick_params(
        axis="both",
        which="minor",
        direction="in",
        top=True,
        right=True,
        length=5,
        width=1.2,
    )
    for spine in ax1.spines.values():
        spine.set_linewidth(1.6)
    ax1.legend(loc="upper left", frameon=False, fontsize=12)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def _plot_sot_peaks(ax, horizons: list[HorizonsRecord], observing_date) -> None:
    peak_indices = max_sot_peak_hours(horizons)
    if not peak_indices:
        return
    labeled = False
    for peak_index in peak_indices:
        peak_hour = datetime_to_ut_hour(horizons[peak_index].time, observing_date)
        if 0 <= peak_hour <= 24:
            ax.axvline(
                x=peak_hour,
                color="0.7",
                linestyle=(0, (8, 6)),
                linewidth=0.8,
                label="max SOT" if not labeled else None,
                zorder=0,
            )
            labeled = True
