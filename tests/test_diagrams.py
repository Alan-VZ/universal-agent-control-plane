"""Keep standalone and embedded architecture maps structurally valid."""

import re
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]


def test_architecture_maps_include_universal_tool_flow():
    standalone = (ROOT / "docs/universal-agent-control-plane.svg").read_text(
        encoding="utf-8"
    )
    html = (ROOT / "docs/universal-agent-control-plane.html").read_text(
        encoding="utf-8"
    )
    embedded = re.search(r"<svg\b.*?</svg>", html, re.DOTALL).group(0)
    for source in (standalone, embedded):
        svg = ElementTree.fromstring(source)
        ids = [element.attrib["id"] for element in svg.iter() if "id" in element.attrib]
        assert len(ids) == len(set(ids))
        for reference in re.findall(r"url\(#([^)]*)\)", source):
            assert reference in ids
        text = " ".join(svg.itertext())
        assert "UACP ToolGateway" in text and "safe replay" in text
        assert svg.attrib["viewBox"] == "0 0 1280 980"
    assert "tool-gateway.md" in html
