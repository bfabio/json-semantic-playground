import difflib
import logging

from filecmp import cmpfiles
from functools import lru_cache
from packaging.version import Version
from pathlib import Path
from typing import List

from pyshacl import validate
from rdflib import Graph

log = logging.getLogger(__name__)

MAX_DEPTH = 5
basedir = Path(__file__).parent


@lru_cache(maxsize=100)
def get_shacl_graph(absolute_path: str) -> Graph:
    if not Path(absolute_path).is_absolute():
        raise ValueError(f"{absolute_path} is not an absolute path")
    log.info(f"Loading SHACL graph from {absolute_path}")
    shacl_graph = Graph()
    shacl_graph.parse(absolute_path, format="turtle")
    return shacl_graph


def validate_shacl(file: str):
    log.info("Validating {}".format(file))
    shacl_graph = None
    rule_file_path = None
    rule_dir = Path(file).parent
    for _ in range(MAX_DEPTH):
        rule_file_candidate = rule_dir / "rules.shacl"
        if rule_file_candidate.exists():
            rule_file_path = rule_file_candidate.absolute().as_posix()
            shacl_graph = get_shacl_graph(rule_file_path)
            log.info(f"Found shacl file: {rule_file_path}")
            break
        if rule_dir == basedir:
            break
        rule_dir = rule_dir.parent
    try:
        # Enable advanced shacl validation: https://www.w3.org/TR/shacl-af/
        is_valid, graph, report_text = validate(
            file.as_posix(), shacl_graph=shacl_graph, advanced=True
        )
        log.info(f"Validation result: {is_valid}, {rule_file_path}, {report_text}")
        if not is_valid:
            exit(1)
    except Exception as e:
        log.error(f"Error validating {file}: {rule_file_path} {e}")
        raise


def validate_directory(ontology_path: Path, errors: List):
    folders = [
        x.name
        for x in ontology_path.glob("*/")
        if x.name != "latest" and x.is_dir()
    ]
    log.debug("Identified folders: %r", (folders,))

    if not folders:
        errors.append(f"No versioned directories found for {ontology_path}")
        return

    versions = [(Version(x), x) for x in folders]
    last_version = sorted(versions, key=lambda v: v[0])[-1][1]

    log.debug("Latest version: %r", (last_version,))

    left_dir = ontology_path / "latest"
    right_dir = ontology_path / last_version

    if not left_dir.exists():
        errors.append(f"ERROR: can't find {left_dir}")
        return

    assert right_dir.exists()

    left = set(f.name for f in left_dir.glob("*"))
    right = set(f.name for f in right_dir.glob("*"))

    only_latest = left - right
    if only_latest:
        errors.append(f"Only in latest/: {', '.join(str(path) for path in only_latest)}")

    only_version_dir = right - left
    if only_version_dir:
        errors.append(
            f"Only in {last_version}/: {', '.join(str(path) for path in only_version_dir)}"
        )

    if right & left:
        _, mismatch, errs = cmpfiles(
            left_dir,
            right_dir,
            right & left,
            shallow=False
        )

        for fname in mismatch:
            diffs = []
            left_path = left_dir / fname
            right_path = right_dir / fname

            with open(left_path) as f_latest, open(right_path) as f_version:
                diff = difflib.unified_diff(
                    f_latest.readlines(),
                    f_version.readlines(),
                    fromfile=left_path.as_posix(),
                    tofile=right_path.as_posix(),
                )
                diffs = "".join(diff)
                if diffs:
                    errors.append(f"ERROR: files are different: {left_path} {right_path}")
                    log.error(diffs)
        if errs:
            errors.append(
                f"ERROR: couldn't check these files: {', '.join(f for f in errs)} (permission issues?)"
            )
