from hashlib import sha256
from importlib.resources import files
import json
from pathlib import Path
import shutil
from tempfile import mkdtemp
from xml.etree.ElementTree import Element, SubElement, tostring

from .engine import exit_code


def render_html(report):
    assets = files("callfence").joinpath("assets")
    payload = json.dumps(report, ensure_ascii=False, allow_nan=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return (assets.joinpath("report.html").read_text(encoding="utf-8")
            .replace("__CSS__", assets.joinpath("report.css").read_text(encoding="utf-8"))
            .replace("__DATA__", payload)
            .replace("__JS__", assets.joinpath("report.js").read_text(encoding="utf-8")))


def render_junit(report):
    cases = report["runs"][-1]["cases"]
    # A bad baseline also fails compare; emit separate suites so CI cannot hide it.
    suites = Element("testsuites")
    for index, run in enumerate(report["runs"]):
        suite = SubElement(suites, "testsuite", name=f"CallFence {index + 1}: {run['spec']['file']}",
                           tests=str(len(cases)), failures=str(run["summary"]["failed"] + run["summary"]["blocked"]))
        for case in run["cases"]:
            testcase = SubElement(suite, "testcase", name=case["id"], classname=report["consumer"])
            if case["status"] != "passed":
                failure = SubElement(testcase, "failure", type=case["status"], message=f"{case['method']} {case['path']}")
                failure.text = "\n".join(f"{item['code']}: {item['message']}" for item in case["findings"] if item["level"] != "passed")
    return tostring(suites, encoding="unicode", xml_declaration=True)


def export_report(report, output_dir):
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise ValueError("Use a new output directory; existing output is never overwritten.")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(mkdtemp(prefix=".callfence-", dir=output_dir.parent))
    try:
        (stage / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        (stage / "report.html").write_text(render_html(report), encoding="utf-8")
        (stage / "junit.xml").write_text(render_junit(report), encoding="utf-8")
        checksums = {name: sha256((stage / name).read_bytes()).hexdigest() for name in ("results.json", "report.html", "junit.xml")}
        manifest = {"run_id": report["run_id"], "exit_code": exit_code(report), "sha256": checksums}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        if output_dir.exists():
            raise ValueError("Output directory appeared during export.")
        stage.rename(output_dir)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return output_dir
