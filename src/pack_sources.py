import os
import tempfile
from datetime import datetime
from zipfile import ZipFile

_DEP_PACKAGE = os.path.join(tempfile.gettempdir(), "deployment_package.zip")


def _get_root_dir() -> str:
    return os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
    )


def _get_version():
    if "VERSION" in os.environ:
        return os.environ["VERSION"]
    else:
        return f"SOURCES. Packed at {datetime.now().isoformat()}"


def _get_sources_dir() -> str:
    return os.path.join(_get_root_dir(), "src")


def zip_sources() -> str:
    if os.path.exists(_DEP_PACKAGE):
        os.remove(_DEP_PACKAGE)
    with ZipFile(_DEP_PACKAGE, "w") as z_file:
        for f in os.listdir(_get_sources_dir()):
            if f not in [
                "lambda_function.py",
                "pack_sources.py",
                "deploy_lambda.py",
            ]:
                if f.endswith(".py"):
                    z_file.write(os.path.join(_get_sources_dir(), f), f)
        with open(os.path.join(_get_sources_dir(), "lambda_function.py"), "r") as f:
            lambda_main_code = f.read()
        with tempfile.NamedTemporaryFile() as tf:
            tf.write(str.encode(lambda_main_code.replace("$VERSION$", _get_version())))
            tf.flush()
            z_file.write(tf.name, "lambda_function.py")
    return _DEP_PACKAGE


if __name__ == "__main__":
    print(zip_sources())
    print(_get_version())
