# Copyright 2026 Thales
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import tempfile
from datetime import datetime
from zipfile import ZipFile

_DEP_PACKAGE = os.path.join(tempfile.gettempdir(), "deployment_package.zip")
_EXCLUDE_FILES = {"lambda_function.py"}
_EXCLUDE_DIRS = {"__pycache__", "rest"}


def _get_version():
    if "VERSION" in os.environ:
        return os.environ["VERSION"]
    else:
        return f"SOURCES. Packed at {datetime.now().isoformat()}"


def _get_sources_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")


def zip_sources() -> str:
    if os.path.exists(_DEP_PACKAGE):
        os.remove(_DEP_PACKAGE)
    src_dir = os.path.abspath(_get_sources_dir())
    with ZipFile(_DEP_PACKAGE, "w") as z_file:
        for root, dirs, files in os.walk(src_dir):
            dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIRS]
            for f in files:
                if not f.endswith(".py"):
                    continue
                abs_path = os.path.join(root, f)
                arc_name = os.path.relpath(abs_path, src_dir)
                if arc_name in _EXCLUDE_FILES:
                    continue
                z_file.write(abs_path, arc_name)
        with open(os.path.join(src_dir, "lambda_function.py"), "r") as f:
            lambda_main_code = f.read()
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(str.encode(lambda_main_code.replace("$VERSION$", _get_version())))
            tf.flush()
            z_file.write(tf.name, "lambda_function.py")
    return _DEP_PACKAGE


if __name__ == "__main__":
    print(zip_sources())
    print(_get_version())
