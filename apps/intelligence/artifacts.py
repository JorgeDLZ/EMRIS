from io import BytesIO
from importlib.metadata import version

LIBRARIES = ("scikit-learn", "pandas", "numpy")


def dump_model(model) -> bytes:
    import joblib

    buffer = BytesIO()
    joblib.dump(model, buffer, compress=3)
    return buffer.getvalue()


def load_model(data: bytes):
    import joblib

    return joblib.load(BytesIO(data))


def library_versions() -> dict[str, str]:
    return {name: version(name) for name in LIBRARIES}
