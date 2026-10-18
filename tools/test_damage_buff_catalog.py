import json
import re

from package.plugin_manager.damage_report.report import build_html


def test_boss_buff_reference_is_report_subset_and_does_not_change_observations():
    buff = {"id": 341204, "piles": 5, "changes": [{"key": 105, "value": -0.75}]}
    payload = {"factorSources": [{"targetBuffs": [buff, {"id": 14001}, {"id": 6020510}]}]}
    before = json.dumps(payload)
    html = build_html(payload)
    data = json.loads(re.search(r'<script id="payload" type="application/json">(.*?)</script>', html, re.S).group(1))
    catalog = data["buffCatalog"]["buffs"]
    assert set(catalog) == {"341204", "14001", "6020510"}
    assert "白骨夫人" in catalog["341204"]["sources"][0]
    assert "枯萎之荷" in catalog["6020510"]["sources"][0]
    assert catalog["14001"]["tag"] == 23
    assert data["factorSources"][0]["targetBuffs"][0]["changes"][0]["value"] == -0.75
    assert json.dumps(payload) == before


def test_catalog_includes_both_side_attribute_sources_and_second_snapshots():
    payload = {"factorSources": [{"self": {"117": [{"label": "Buff：402083（4层）"}]}}],
               "other": {"factorSources": [{"target": {"105": [{"label": "Buff：341204 · 旧关联（1层）"}]}}]},
               "pvp": {"attrSeconds": [{"selfSources": {"3": [{"label": "Buff：340210（1层）"}]},
                                        "otherSources": {"104": [{"label": "Buff：200825（1层）"}]}}]}}
    html = build_html(payload)
    data = json.loads(re.search(r'<script id="payload" type="application/json">(.*?)</script>', html, re.S).group(1))
    assert set(data["buffCatalog"]["buffs"]) == {"402083", "341204", "340210", "200825"}
