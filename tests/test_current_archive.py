from datetime import date
from pathlib import Path

import pytest

from spherex_helium import cli, discovery


DAY = date(2025, 12, 21)


def uri(release, exposure, image=2, version=27, stamp="2026-211"):
    root = f"{release}/level2/2025W51_2A/l2b-v{version}-{stamp}/1/"
    filename = f"level2_2025W51_2A_{exposure}_{image}D1_spx_l2b-v{version}-{stamp}.fits"
    return f"s3://nasa-irsa-spherex/{root}{filename}"


def test_current_union_prefers_dr1_and_keeps_distinct_images(monkeypatch):
    dr1 = uri("dr1", "0590")
    older_dr1 = uri("dr1", "0590", version=9)
    newer_qr3 = uri("qr3", "0590", version=28)
    other_image = uri("qr3", "0590", image=1)
    other_exposure = uri("qr3", "0650")
    older_qr3 = uri("qr3", "0650", stamp="2026-205")
    found = {
        "dr1/level2": [older_dr1, dr1],
        "qr3/level2": [newer_qr3, other_image, older_qr3, other_exposure],
    }
    calls = []

    def mocked(day, *, root_prefix, **kwargs):
        assert day == DAY
        assert kwargs == {"bucket": "example", "week_padding": 2, "timeout_s": 8}
        calls.append(root_prefix)
        return found[root_prefix]

    monkeypatch.setattr(discovery, "discover_s3_by_date", mocked)
    kwargs = dict(data_source="current", s3_bucket="example",
                  s3_planning_period_week_padding=2, timeout_s=8)
    result = discovery.discover_observation_uris(DAY, **kwargs)
    assert result == [other_image, dr1, other_exposure]
    assert set(calls) == {"dr1/level2", "qr3/level2"}
    assert discovery.discover_observation_uris(DAY, **kwargs, max_files=2) == result[:2]


@pytest.mark.parametrize("release", discovery.CURRENT_S3_RELEASES)
def test_current_finds_dates_when_only_one_release_has_data(monkeypatch, release):
    target = uri(release, "0590")
    monkeypatch.setattr(discovery, "discover_s3_by_date", lambda day, *, root_prefix, **_:
                       [target] if root_prefix == f"{release}/level2" else [])
    assert discovery.discover_current_s3_by_date(DAY) == [target]


def test_legacy_auto_still_queries_qr2_only(monkeypatch):
    def mocked(day, **kwargs):
        assert day == DAY
        assert kwargs["root_prefix"] == "qr2/level2"
        assert kwargs["max_files"] == 1
        return [uri("qr2", "0590")]

    monkeypatch.setattr(discovery, "discover_s3_by_date", mocked)
    assert discovery.discover_observation_uris(DAY, max_files=1) == [uri("qr2", "0590")]


def test_current_cli_keeps_legacy_default_output_separate(monkeypatch):
    configs = []

    def run_day(config):
        configs.append(config)
        return discovery_result

    from types import SimpleNamespace

    discovery_result = SimpleNamespace(output_path="plot.png", count=0, skipped=0, observations=[])
    monkeypatch.setattr(cli, "run_day", run_day)
    cli.main([DAY.isoformat()])
    cli.main([DAY.isoformat(), "--data-source", "current"])
    assert configs[0].data_source == "auto"
    assert configs[0].collection == "spherex_qr2"
    assert configs[0].output_path == Path("spherex_helium_20251221.png")
    assert configs[1].data_source == "current"
    assert configs[1].output_path == Path("spherex_helium_20251221_dr1_qr3.png")
    with pytest.raises(SystemExit):
        cli.main([DAY.isoformat(), "--data-source", "current", "--s3-root-prefix", "qr3/level2"])


@pytest.mark.parametrize(
    ("day", "release", "period", "exposure", "stamp"),
    [
        (DAY, "dr1", "2025W51_2A", "0531_1D1", "2026-211"),
        (date(2026, 5, 21), "qr3", "2026W21_1A", "0505_3D1", "2026-268"),
    ],
)
def test_current_accepts_real_retry_names_and_preserves_release_preference(
    monkeypatch, day, release, period, exposure, stamp,
):
    def product(rel, tag):
        return (
            f"s3://nasa-irsa-spherex/{rel}/level2/{period}/{tag}/1/"
            f"level2_{period}_{exposure}_spx_{tag}.fits"
        )

    retry = product(release, f"l2b_retry-v27-{stamp}")
    older_regular = product(release, f"l2b-v26-{stamp}")
    duplicate_other_release = (
        product("qr3", f"l2b-v29-{stamp}") if release == "dr1" else None
    )
    entries = {f"{release}/level2": [older_regular, retry]}
    if duplicate_other_release:
        entries["qr3/level2"] = [duplicate_other_release]
    monkeypatch.setattr(discovery, "discover_s3_by_date", lambda _, *, root_prefix, **__:
                        entries.get(root_prefix, []))
    assert discovery.discover_observation_uris(day, data_source="current", max_files=1) == [retry]


@pytest.mark.parametrize(("data_source", "reported_other"), [("current", 2), ("auto", 1)])
def test_horizons_summary_and_labels(monkeypatch, tmp_path, capsys, data_source, reported_other):
    from datetime import datetime, timezone

    from spherex_helium import pipeline
    from spherex_helium.types import HorizonsRecord, ObservationResult, RunConfig

    keys = [f"exposure_{i}" for i in range(4)]
    now = datetime(2025, 12, 21, tzinfo=timezone.utc)
    records = {
        key: HorizonsRecord(time=now, obs_sub_lat=latitude)
        for key, latitude in zip(keys, (81, -82, 55))
    }
    monkeypatch.setattr(pipeline, "discover_observation_uris", lambda *args, **kwargs: keys)
    monkeypatch.setattr(pipeline, "_match_uris_by_horizons_orbit", lambda *args: records)
    monkeypatch.setattr(pipeline, "plot_day", lambda *args, **kwargs: None)

    def fake_process(key, config, *, forced_label, **kwargs):
        return ObservationResult(now, 500, key, key, forced_label)

    monkeypatch.setattr(pipeline, "process_uri", fake_process)
    result = pipeline.run_day(RunConfig(
        DAY, tmp_path / "output.png", data_source=data_source,
        fetch_horizons=False, process_workers=1,
    ))
    assert [obs.label for obs in result.observations] == ["North", "South", "Other", "Other"]
    assert f"North=1, South=1, Other={reported_other}" in capsys.readouterr().err
