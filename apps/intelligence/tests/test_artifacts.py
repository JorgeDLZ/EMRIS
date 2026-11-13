from apps.intelligence.artifacts import dump_model, library_versions, load_model
from ml.profiles import train_profiles
from ml.tests.conftest import make_synthetic_frame


def test_round_trip_keeps_predictions():
    frame = make_synthetic_frame()
    model = train_profiles(frame).model
    restored = load_model(dump_model(model))
    assert restored.assign(frame) == model.assign(frame)


def test_library_versions_keys():
    versions = library_versions()
    assert set(versions) == {"scikit-learn", "pandas", "numpy"}
    assert all(isinstance(value, str) and value for value in versions.values())
