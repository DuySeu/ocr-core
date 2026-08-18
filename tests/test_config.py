import pytest

from core.config import Config, ConfigError, load, pipeline_version


def test_defaults_validate():
    Config().validate()


def test_unknown_layout_rejected():
    with pytest.raises(ConfigError):
        Config(layout="bogus").validate()


def test_unknown_table_rejected():
    with pytest.raises(ConfigError):
        Config(table="bogus").validate()


def test_unknown_step_rejected():
    with pytest.raises(ConfigError):
        Config(preprocess_steps=["bogus"]).validate()


def test_unknown_output_rejected():
    with pytest.raises(ConfigError):
        Config(outputs=["pdf"]).validate()


def test_tesseract_layout_requires_tesseract_engine():
    with pytest.raises(ConfigError, match="engine"):
        Config(layout="tesseract", engine="paddleocr").validate()


def test_none_layout_allows_any_engine():
    Config(layout="none", engine="paddleocr").validate()


@pytest.mark.parametrize("threshold", [-0.1, 1.1])
def test_qa_threshold_out_of_range_rejected(threshold):
    with pytest.raises(ConfigError, match="qa_threshold"):
        Config(qa_threshold=threshold).validate()


def test_precedence_overrides_over_base():
    cfg = load(None, {"dpi": 150}, base=Config())
    assert cfg.dpi == 150


def test_unknown_config_key_rejected():
    with pytest.raises(ConfigError, match="ground_truth"):
        load(None, {"ground_truth": "./x"}, base=Config())


def test_ground_truth_dir_is_a_real_config_field():
    cfg = load(None, {"ground_truth_dir": "./gt"}, base=Config())
    assert cfg.ground_truth_dir == "./gt"


def test_pipeline_version_changes_when_dpi_changes():
    a = pipeline_version(Config(dpi=300))
    b = pipeline_version(Config(dpi=200))
    assert a != b


def test_pipeline_version_is_stable_for_the_same_config():
    assert pipeline_version(Config()) == pipeline_version(Config())


def test_pipeline_version_ignores_path_fields():
    a = pipeline_version(Config(output_dir="./output"))
    b = pipeline_version(Config(output_dir="./somewhere-else", review_dir="./r"))
    assert a == b


def test_pipeline_version_reads_engine_langs_layout_table():
    version = pipeline_version(Config(engine="tesseract", langs=["vie", "eng"]))
    assert version.startswith("tesseract_vie+eng_tesseract_cv_")
