import json

import pytest

from evaluate import recognition
from evaluate.__main__ import main
from evaluate.config import ConfigError, load_config
from evaluate.recognition.report import render_markdown

TABLE = "<table><tr><td>Kỳ hạn</td><td>Lãi suất</td></tr></table>"


# Lay out a pred dir and a GT dataset under tmp_path, from {doc_id: text} maps.
@pytest.fixture
def workspace(tmp_path):
    def _build(predictions, gold):
        pred_dir, gt_dir = tmp_path / "pred", tmp_path / "gt"
        pred_dir.mkdir()
        gt_dir.mkdir()
        for doc_id, text in predictions.items():
            # Core-pipeline output nests each document in its own directory
            (pred_dir / doc_id).mkdir()
            (pred_dir / doc_id / f"{doc_id}.md").write_text(text, encoding="utf-8")
        for doc_id, text in gold.items():
            (gt_dir / f"{doc_id}.md").write_text(text, encoding="utf-8")
            (gt_dir / f"{doc_id}.json").write_text(
                json.dumps({"doc_id": doc_id, "text_file": f"{doc_id}.md"}), encoding="utf-8"
            )
        return pred_dir, gt_dir

    return _build


# Run the tier with the defaults the CLI uses.
def run(pred_dir, gt_dir, **kwargs):
    return recognition.run(pred_dir, gt_dir, label="engine-x", table_threshold=0.5, **kwargs)


def test_a_prediction_is_paired_with_the_record_of_the_same_stem(workspace):
    report = run(*workspace({"a": "Bên vay cam kết"}, {"a": "Bên vay cam kết"}))

    [document] = report.documents
    assert document.doc_id == "a"
    assert document.wer.wer == 0.0


def test_unpaired_documents_are_named_on_both_sides(workspace):
    report = run(*workspace({"a": "x", "only_pred": "x"}, {"a": "x", "only_gold": "x"}))

    assert [d.doc_id for d in report.documents] == ["a"]
    assert report.unpaired == [
        ("only_gold", recognition.NO_PREDICTION_REASON),
        ("only_pred", recognition.NO_GOLD_REASON),
    ]


def test_two_predictions_sharing_a_stem_is_an_error_not_a_silent_pick(workspace):
    pred_dir, gt_dir = workspace({"a": "x"}, {"a": "x"})
    (pred_dir / "a.md").write_text("y", encoding="utf-8")

    with pytest.raises(recognition.PairingError, match="share the stem"):
        run(pred_dir, gt_dir)


def test_aside_blocks_below_the_marker_are_not_scored(workspace):
    report = run(*workspace({"a": "Bên vay\n<!-- ann-aside -->\nTrang 1"}, {"a": "Bên vay"}))

    assert report.documents[0].wer.errors == 0


def test_the_pooled_row_sums_words_rather_than_averaging_document_rates(workspace):
    report = run(*workspace({"a": "x", "b": "a b c d"}, {"a": "y", "b": "a b c d"}))

    # Per-document rates 1.0 and 0.0 would average 0.5; pooled is 1 error over 5 words
    assert report.pooled_wer.wer == pytest.approx(0.2)


def test_tables_are_paired_and_counted(workspace):
    report = run(*workspace({"a": f"x\n{TABLE}"}, {"a": f"x\n{TABLE}\n{TABLE}"}))

    tables = report.documents[0].tables
    assert (tables.n_matched, tables.n_gold, tables.n_pred) == (1, 2, 1)
    assert tables.teds == pytest.approx(1.0)


def test_doc_restricts_the_run_to_one_document(workspace):
    report = run(*workspace({"a": "x", "b": "x"}, {"a": "x", "b": "x"}), doc_id="b")

    assert [d.doc_id for d in report.documents] == ["b"]
    assert report.unpaired == []


def test_the_report_renders_every_section(workspace):
    markdown = render_markdown(run(*workspace({"a": "x"}, {"a": "x", "b": "x"})))

    assert "## WER" in markdown
    assert "| **pooled** | 0.0000 | 1 | 0 |" in markdown
    assert "| a | - | 0 | 0 | 0 | |" in markdown
    assert "- `b`: ground truth has no prediction" in markdown


def test_the_cli_writes_the_report_under_tier_label_and_dataset(workspace, tmp_path, monkeypatch):
    pred_dir, gt_dir = workspace({"a": "x"}, {"a": "x"})
    monkeypatch.setattr("evaluate.__main__.RESULTS_DIR", tmp_path / "results")

    code = main(["recognition", "--pred", str(pred_dir), "--gt", str(gt_dir), "--label", "chandra"])

    assert code == 0
    assert (tmp_path / "results" / "recognition" / "chandra" / "gt.md").exists()


@pytest.mark.parametrize("tier", ["layout", "extraction"])
def test_an_unimplemented_tier_fails_by_name(workspace, tier):
    pred_dir, gt_dir = workspace({}, {})

    assert main([tier, "--pred", str(pred_dir), "--gt", str(gt_dir)]) == 1


def test_directories_fall_back_to_config_yaml(tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "gt").mkdir()
    config = tmp_path / "config.yaml"
    config.write_text(f"output_dir: {tmp_path / 'out'}\nground_truth_dir: {tmp_path / 'gt'}\n", encoding="utf-8")

    loaded = load_config(config)

    assert (loaded.pred_dir, loaded.gt_dir) == (tmp_path / "out", tmp_path / "gt")


def test_a_config_missing_a_directory_key_says_which(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("output_dir: .\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="ground_truth_dir"):
        load_config(config, pred_dir=tmp_path)
