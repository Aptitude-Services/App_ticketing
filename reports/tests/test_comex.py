"""COMEX PowerPoint : données d'un client final sur une période libre, fichier généré, accès."""
import datetime
import io

import pytest
from django.urls import reverse
from pptx import Presentation

from reports import services as R
from reports.comex.data import comex_data, quarter_of
from reports.comex.deck import build_comex
from reports.models import Report

from .test_reports import w  # noqa: F401  (fixture partagée)

pytestmark = pytest.mark.django_db
T4 = (datetime.date(2026, 10, 1), datetime.date(2026, 12, 31))
# Textes de l'exemple du modèle qui ne doivent jamais se retrouver dans un COMEX généré.
SAMPLE_TEXTS = ["Société Exemple", "MNT-2025-0142", "SAN-01", "Lyon", "Grenoble", "FW-ENT-01", "IDP-01",
                "27 / 31", "99,92"]


def _quarterly(w, **data):
    r = R.create_report(w["tech"], Report.Kind.QUARTERLY, w["contract"], end_client=w["end"], year=2026, quarter=4)
    r.data = {**r.data, **data}
    r.save()
    R.submit(w["tech"], r)
    R.validate(w["boss"], r)
    return r


def _deck(content):
    prs = Presentation(io.BytesIO(content))
    texts = []
    for slide in prs.slides:
        ids = [int(x) for x in slide.shapes._spTree.xpath(".//p:cNvPr/@id")]
        assert len(ids) == len(set(ids)), "identifiants de formes en double"
        parts = []
        for sh in slide.shapes:
            if sh.has_text_frame:
                parts.append(sh.text_frame.text)
            if getattr(sh, "has_table", False) and sh.has_table:
                parts += [c.text for row in sh.table.rows for c in row.cells]
        if slide.has_notes_slide:
            parts.append(slide.notes_slide.notes_text_frame.text)
        texts.append("\n".join(parts))
    return prs, texts


def test_quarter_detection():
    assert quarter_of(*T4) == (4, 2026)
    assert quarter_of(datetime.date(2026, 10, 1), datetime.date(2026, 11, 10)) is None


def test_data_combines_tickets_and_quarterly_inputs(w):
    _quarterly(w, availability="99,95", headline="Parc sain", highlights=[["Migration réussie"]],
               recommendations=[["Superviser les certificats", "3 incidents", "élevé", "faible"]],
               action_plan=[["Alerte certificats", "Haute", "Aptitude", "15/01/2027", "En cours"]],
               decisions=[["Extension du stockage", "Valider le budget"]], next_point="Point T1 2027")
    d = comex_data(w["esn"], w["end"], *T4)
    assert d["tickets_total"] == 1 and d["tickets_resolved"] == 1
    assert d["contracts"] == [w["contract"].reference]
    assert d["availability"] == 99.95 and d["headline"] == "Parc sain"
    assert d["highlights"] == ["Migration réussie"]
    assert d["decisions"] == [{"title": "Extension du stockage", "detail": "Valider le budget"}]
    assert d["quarter"] == (4, 2026)


def test_draft_quarterly_reports_are_ignored(w):
    r = R.create_report(w["tech"], Report.Kind.QUARTERLY, w["contract"], end_client=w["end"], year=2026, quarter=4)
    r.data = {**r.data, "headline": "Brouillon non validé"}
    r.save()
    assert comex_data(w["esn"], w["end"], *T4)["headline"] != "Brouillon non validé"


def test_full_deck_is_filled_without_sample_leftovers(w):
    _quarterly(w, availability="99,95", availability_months=[["Octobre", "99,97"], ["Novembre", "99,93"]],
               done_kpis=[["12", "correctifs appliqués"]], done_actions=[["Correctifs critiques appliqués"]],
               recommendations=[["Superviser les certificats", "3 incidents", "élevé", "faible"],
                                ["Étendre le stockage", "Saturation", "élevé", "élevé"]],
               action_plan=[["Alerte certificats", "Haute", "Aptitude", "15/01/2027", "En cours"],
                            ["Budget stockage", "Haute", "Client", "28/02/2027", "Décision attendue"]],
               decisions=[["Extension du stockage", "Valider le budget"]], next_point="Point T1 2027")
    content = build_comex(comex_data(w["esn"], w["end"], *T4))
    prs, texts = _deck(content)
    assert len(prs.slides) == 11
    whole = "\n".join(texts)
    assert "Banque Lagune" in texts[0] and "Hudson" in texts[0] and "T4" in texts[0]
    for sample in SAMPLE_TEXTS:
        assert sample not in whole, sample
    assert "Superviser les certificats" in whole and "Alerte certificats" in whole
    assert "Une décision attendue" in whole and "Point T1 2027" in whole


def test_deck_without_quarterly_report_omits_manual_slides(w):
    content = build_comex(comex_data(w["esn"], w["end"], datetime.date(2026, 8, 10), datetime.date(2026, 11, 10)))
    prs, texts = _deck(content)
    assert len(prs.slides) == 6  # couverture, synthèse, tickets, engagements, incidents, préventif
    whole = "\n".join(texts)
    assert "RAPPORT DE PILOTAGE" in texts[0]
    for sample in SAMPLE_TEXTS:
        assert sample not in whole, sample


def test_page_is_reserved_to_super_admin_and_managers(w):
    c = w["client"]
    for who in ("tech", "esn_admin", "end_user"):
        c.force_login(w[who])
        assert c.get(reverse("comex")).status_code == 404
    c.force_login(w["boss"])
    page = c.get(reverse("comex")).content.decode()
    assert "Hudson → Banque Lagune" in page
    resp = c.post(reverse("comex"), {"scope": f"{w['esn'].pk}:{w['end'].pk}", "start": "2026-10-01",
                                     "end": "2026-12-31"})
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("application/vnd.openxmlformats-officedocument.presentationml")
    assert 'filename="COMEX_Banque-Lagune_20261001-20261231.pptx"' in resp["Content-Disposition"]
    Presentation(io.BytesIO(resp.content))


def test_form_rejects_bad_scope_and_period(w):
    c = w["client"]
    c.force_login(w["boss"])
    resp = c.post(reverse("comex"), {"scope": f"{w['esn'].pk}:{w['end'].pk}", "start": "2026-12-31",
                                     "end": "2026-10-01"})
    assert resp.status_code == 200 and resp["Content-Type"].startswith("text/html")
    resp = c.post(reverse("comex"), {"scope": "999:999", "start": "2026-10-01", "end": "2026-12-31"})
    assert resp["Content-Type"].startswith("text/html")
