"""Génération du COMEX PowerPoint à partir du modèle `modele_comex.pptx`.

Le modèle (couleurs, polices, graphiques natifs, mises en page) est conservé : chaque diapositive
est remplie par le nom de ses formes. Les blocs répétés (sites, recommandations, actions,
décisions…) sont dupliqués ou retirés selon les données ; une diapositive sans aucune donnée
est omise. Le fichier produit reste entièrement modifiable dans PowerPoint.
"""
import base64
import copy
import datetime
import io
from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_THEME_COLOR
from pptx.util import Emu, Inches, Pt

from .data import MONTHS_SHORT, fmt_pct

TEMPLATE = Path(__file__).with_name("modele_comex.pptx")
GOOD, BAD = MSO_THEME_COLOR.ACCENT_3, MSO_THEME_COLOR.ACCENT_6
CELL = {"OK": ("E8F1E7", "4D704C"), "Attention": ("FDEEE0", "A85A25")}
CELL_NONE = ("ECEEF0", "555B61")
NUMBERS = {1: "Une", 2: "Deux", 3: "Trois", 4: "Quatre", 5: "Cinq"}


# --- Outils ----------------------------------------------------------------------------------------

def _shape(slide, name):
    for sh in slide.shapes:
        if sh.name == name:
            return sh
    raise KeyError(name)


def _cut(text, limit):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _set(shape, text):
    """Remplace le texte en gardant la mise en forme du premier paragraphe et de sa première portion."""
    tf = shape.text_frame
    paras = tf.paragraphs
    for p in paras[1:]:
        p._p.getparent().remove(p._p)
    p = paras[0]
    runs = p.runs
    if runs:
        runs[0].text = str(text)
        for r in runs[1:]:
            r._r.getparent().remove(r._r)
    else:
        p.text = str(text)


def _set_lines(shape, lines):
    """Une ligne par paragraphe, sur le modèle du premier paragraphe (puces conservées)."""
    tf = shape.text_frame
    first = tf.paragraphs[0]._p
    for p in tf.paragraphs[1:]:
        p._p.getparent().remove(p._p)
    lines = [str(x) for x in lines] or [""]
    _set(shape, lines[0])
    anchor = first
    for line in lines[1:]:
        new = copy.deepcopy(first)
        anchor.addnext(new)
        anchor = new
        t = new.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/main}t")
        if t:
            t[0].text = line


def _color(shape, color):
    """Couleur du texte de toutes les portions (couleur de thème ou RVB hexadécimal)."""
    for p in shape.text_frame.paragraphs:
        for r in p.runs:
            if isinstance(color, str):
                r.font.color.rgb = RGBColor.from_string(color)
            else:
                r.font.color.theme_color = color


def _fill(shape, color):
    shape.fill.solid()
    if isinstance(color, str):
        shape.fill.fore_color.rgb = RGBColor.from_string(color)
    else:
        shape.fill.fore_color.theme_color = color


def _remove(*shapes):
    for sh in shapes:
        el = sh._element
        el.getparent().remove(el)


def _next_id(slide):
    ids = [int(x) for x in slide.shapes._spTree.xpath(".//p:cNvPr/@id")]
    return max(ids + [1]) + 1


def _clone(slide, shape, left=None, top=None, width=None):
    el = copy.deepcopy(shape._element)
    el.xpath("./*[1]/p:cNvPr")[0].set("id", str(_next_id(slide)))
    slide.shapes._spTree.append(el)
    new = slide.shapes[-1]
    if left is not None:
        new.left = Emu(int(left))
    if top is not None:
        new.top = Emu(int(top))
    if width is not None:
        new.width = Emu(int(width))
    return new


def _same_box(slide, shape):
    """Zone de texte posée exactement sur une forme (pastille numérotée, cellule…)."""
    for sh in slide.shapes:
        if sh is not shape and sh.has_text_frame and sh.left == shape.left and sh.top == shape.top \
                and sh.shape_type == 17:
            return sh
    return None


def _unique_ids(slide):
    """Identifiants de formes uniques (le modèle d'origine en a en double : numéro de page)."""
    seen = set()
    nodes = slide.shapes._spTree.xpath(".//p:cNvPr")
    top = max([int(n.get("id")) for n in nodes] + [1])
    for node in nodes:
        sid = int(node.get("id"))
        if sid in seen:
            top += 1
            node.set("id", str(top))
            sid = top
        seen.add(sid)


def _drop_slide(prs, slide):
    sld_ids = prs.slides._sldIdLst
    for sld_id in list(sld_ids):
        if prs.part.related_part(sld_id.rId) is slide.part:
            prs.part.drop_rel(sld_id.rId)
            sld_ids.remove(sld_id)
            return


def _chart(shape, categories, series):
    data = CategoryChartData()
    data.categories = categories or ["—"]
    for name, values in series:
        data.add_series(name, values or [0])
    shape.chart.replace_data(data)


def _date(value):
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    return None


# --- Diapositives ----------------------------------------------------------------------------------

def _cover(slide, d):
    q = d["quarter"]
    start, end = d["start"], d["end"]
    _set(_shape(slide, "Text 1"), "RAPPORT TRIMESTRIEL — COMITÉ DE DIRECTION" if q
         else "RAPPORT DE PILOTAGE — COMITÉ DE DIRECTION")
    _set(_shape(slide, "Text 3"), _cut(d["end_client"], 60))
    contracts = ", ".join(d["contracts"]) or "—"
    label = "Contrat" if len(d["contracts"]) <= 1 else "Contrats"
    _set(_shape(slide, "Text 4"), _cut(f"{d['esn']} · Période du {start:%d/%m/%Y} au {end:%d/%m/%Y} · "
                                       f"{label} {contracts}", 120))
    big = _shape(slide, "Text 5")
    if q:
        _set(big, f"T{q[0]}")
        _set(_shape(slide, "Text 6"), str(q[1]))
    else:
        _set(big, f"{MONTHS_SHORT[start.month - 1]}–{MONTHS_SHORT[end.month - 1]}")
        for r in big.text_frame.paragraphs[0].runs:
            r.font.size = Pt(54)
        _set(_shape(slide, "Text 6"), str(end.year) if start.year == end.year else f"{start.year}–{end.year}")
    logo = d.get("esn_logo") or ""
    if logo.startswith(("data:image/png", "data:image/jpeg", "data:image/gif")):
        raw = base64.b64decode(logo.split(",", 1)[1])
        pic = slide.shapes.add_picture(io.BytesIO(raw), Inches(0.70), Inches(6.20), height=Inches(0.65))
        pic.name = "Logo ESN"
        if pic.width > Inches(3.0):
            ratio = Inches(3.0) / pic.width
            pic.width, pic.height = Inches(3.0), int(pic.height * ratio)


def _synthesis(slide, d):
    met = d["resolution_pct"] is None or d["resolution_pct"] >= d["resolution_target"]
    _set(_shape(slide, "Text 0"), "Des engagements tenus sur la période" if met
         else "Des engagements globalement tenus, avec des points d'attention")
    _set(_shape(slide, "Text 3"), _cut(d["headline"], 110))

    av, target = d["availability"], d["availability_target"]
    _set(_shape(slide, "Text 5"), fmt_pct(av, 2) if av is not None else "—")
    _color(_shape(slide, "Text 5"), GOOD if av is not None and av >= target else (BAD if av is not None else
                                                                                 MSO_THEME_COLOR.TEXT_1))
    _set(_shape(slide, "Text 7"), f"Objectif {fmt_pct(target, 2)}" if av is not None else "Non renseignée")

    _set(_shape(slide, "Text 9"), f"{d['tickets_resolved']} / {d['tickets_total']}")
    _set(_shape(slide, "Text 11"), f"{d['tickets_open']} encore ouvert{'s' if d['tickets_open'] > 1 else ''}"
         if d["tickets_open"] else "Aucun ticket ouvert")

    _set(_shape(slide, "Text 13"), fmt_pct(d["resolution_pct"]))
    _color(_shape(slide, "Text 13"), GOOD if met else BAD)
    _set(_shape(slide, "Text 15"), f"Objectif {fmt_pct(d['resolution_target'])}")

    planned = d["visits_planned"]
    _set(_shape(slide, "Text 17"), f"{d['visits_done']} / {planned}" if planned else str(d["visits_done"]))
    _set(_shape(slide, "Text 19"), _cut(d["visits_note"], 45) or ("Visites planifiées non renseignées"
                                                                    if not planned else ""))

    _set_lines(_shape(slide, "Text 22"), [_cut(x, 110) for x in d["highlights"][:4]])
    _set_lines(_shape(slide, "Text 25"), [_cut(x, 110) for x in d["attention"][:4]] or ["Aucun point d'attention."])


def _tickets(slide, d):
    total, done = d["tickets_total"], d["tickets_resolved"]
    pct = round(done * 100 / total) if total else 0
    _set(_shape(slide, "Text 0"), f"{total} ticket{'s' if total > 1 else ''} traité{'s' if total > 1 else ''} "
                                  f"sur la période, {pct} % résolus" if total else "Aucun ticket sur la période")
    months = d["months"]
    _chart(_shape(slide, "Chart 0"), [m["label"] for m in months],
           [("Ouverts", [m["opened"] for m in months]), ("Résolus", [m["resolved"] for m in months])])
    statuses = [(name, n) for name, n in d["statuses"] if n] or [("Aucun ticket", 0)]
    _chart(_shape(slide, "Chart 1"), [s[0] for s in statuses], [("Statut", [s[1] for s in statuses])])
    for p, name in zip(d["priorities"], ("Text 7", "Text 9", "Text 11", "Text 13")):
        _set(_shape(slide, name), f"{p['resolved']} / {p['opened']}")


def _bar(slide, n, value, target, low, value_text, value_box, target_box, status_box):
    track = _shape(slide, f"Piste {n}")
    bar = _shape(slide, f"Valeur {n}")
    mark = _shape(slide, f"Objectif {n}")

    def x(v):
        return track.left + int(track.width * max(0.0, min(1.0, (v - low) / (100 - low))))

    mark.left = Emu(x(target) - mark.width // 2)
    _set(_shape(slide, target_box), f"Objectif {fmt_pct(target, 2 if target % 1 else 1)}")
    if value is None:
        _remove(bar)
        _set(_shape(slide, value_box), "—")
        _set(_shape(slide, status_box), "Non renseigné")
        return
    met = value >= target
    bar.width = Emu(max(Inches(0.05), x(value) - track.left))
    _fill(bar, GOOD if met else BAD)
    _set(_shape(slide, value_box), value_text)
    _color(_shape(slide, value_box), GOOD if met else BAD)
    _set(_shape(slide, status_box), "Objectif atteint" if met else "Sous l'objectif")
    _color(_shape(slide, status_box), GOOD if met else BAD)


def _commitments(slide, d):
    rt = d["resolution_target"]
    checks = [(d["response_pct"], d["response_target"]), (d["resolution_pct"], rt)]
    av, at = d["availability"], d["availability_target"]
    misses = [v for v, t in checks + [(av, at)] if v is not None and v < t]
    _set(_shape(slide, "Text 0"), "Les engagements de service sont tenus" if not misses
         else "Des engagements à rattraper sur la période")
    _bar(slide, 1, d["response_pct"], d["response_target"], max(0, d["response_target"] - 10),
         fmt_pct(d["response_pct"]), "Text 4", "Text 8", "Text 9")
    _bar(slide, 2, d["resolution_pct"], rt, max(0, rt - 10), fmt_pct(d["resolution_pct"]),
         "Text 11", "Text 15", "Text 16")
    _bar(slide, 3, av, at, max(0, at - 4 * (100 - at)), fmt_pct(av, 2), "Text 18", "Text 22", "Text 23")

    chart = _shape(slide, "Chart 0")
    months = d["availability_months"]
    if months:
        _chart(chart, [f"{m}\n{fmt_pct(v, 2)}" for m, v in months],
               [("Disponibilité", [v for _m, v in months]), ("Objectif", [at for _m in months])])
    else:
        note = _clone(slide, _shape(slide, "Text 28"), top=chart.top + Inches(0.9))
        _set_lines(note, ["Disponibilité mensuelle non renseignée dans les rapports trimestriels."])
        _remove(chart)
    _set_lines(_shape(slide, "Text 28"), [_cut(x, 95) for x in d["overruns"][:3]] or ["Aucun dépassement."])
    _set(_shape(slide, "Text 27"), "Dépassements de la période")


def _incidents(slide, d):
    causes, eq = d["causes"], d["equipment"]
    _set(_shape(slide, "Text 0"), f"Incidents : {', '.join(c[0].lower() for c in causes[:2])} en tête"
         if causes else "Incidents de la période")
    _set(_shape(slide, "Text 2"), "Causes des incidents (rapports curatifs)")
    _chart(_shape(slide, "Chart 0"), [_cut(c[0], 40) for c in causes] or ["Aucun rapport curatif"],
           [("Causes", [c[1] for c in causes] or [0])])
    _chart(_shape(slide, "Chart 1"), [_cut(e[0], 40) for e in eq] or ["Aucun équipement cité"],
           [("Équipements les plus concernés", [e[1] for e in eq] or [0])])
    cards = [("Carte récurrence 1", "Text 7", "Text 8", "Text 9"), ("Carte récurrence 2", "Text 11", "Text 12",
                                                                     "Text 13"),
             ("Carte récurrence 3", "Text 15", "Text 16", "Text 17")]
    rec = d["recurring"][:3]
    if not rec:
        _remove(_shape(slide, "Text 5"))
    for i, names in enumerate(cards):
        shapes = [_shape(slide, n) for n in names]
        if i >= len(rec):
            _remove(*shapes)
            continue
        r = rec[i]
        _set(shapes[1], _cut(r["name"], 55))
        count = str(r["count"]).strip()
        _set(shapes[2], f"{count} fois" if count.isdigit() else _cut(count, 10))
        _set(shapes[3], _cut(r["action"], 80))


def _health_rows(slide):
    rows = {}
    for sh in slide.shapes:
        top = sh.top / 914400
        if 3.9 <= top <= 6.0 and (sh.name.startswith("Cellule") or (sh.has_text_frame and sh.shape_type == 17
                                                                     and sh.left / 914400 < 12.9)):
            if sh.width / 914400 > 11:  # note de bas de carte
                continue
            rows.setdefault(round((top - 4.0) / 0.85), []).append(sh)
    return [rows[k] for k in sorted(rows)]


def _preventive(slide, d):
    c = d["controls"]
    total, ok = c.get("total", 0), c.get("ok", 0)
    anomalies = c.get("watch", 0) + c.get("ko", 0)
    _set(_shape(slide, "Text 0"), f"Préventif : {ok} contrôles conformes sur {total}" if total
         else "Préventif : aucune visite validée sur la période")
    planned = d["visits_planned"]
    _set(_shape(slide, "Text 2"), f"{d['visits_done']} / {planned}" if planned else str(d["visits_done"]))
    _set(_shape(slide, "Text 5"), str(total))
    _set(_shape(slide, "Text 8"), str(anomalies))
    _set(_shape(slide, "Text 11"), f"{ok} / {total}" if total else "—")
    _set(_shape(slide, "Text 12"), "Contrôles conformes")

    rows = _health_rows(slide)
    health = d["health"]
    for i, shapes in enumerate(rows):
        if i >= len(health):
            _remove(*shapes)
            continue
        site = health[i]
        shapes.sort(key=lambda s: (s.left, 0 if s.name.startswith("Cellule") else 1))
        label, rest = shapes[0], shapes[1:]
        _set(label, _cut(site["site"], 40))
        for j in range(0, len(rest), 2):
            cell, text = rest[j], rest[j + 1]
            state = site["states"][j // 2] if j // 2 < len(site["states"]) else "—"
            bg, fg = CELL.get(state, CELL_NONE)
            _fill(cell, bg)
            _set(text, state if state in ("OK", "Attention", "N/A") else "—")
            _color(text, fg)
    note = _shape(slide, "Text 60")
    extra = len(health) - len(rows)
    lines = []
    if not health:
        lines.append("Aucune visite préventive validée sur la période.")
    if extra > 0:
        lines.append(f"{extra} autre(s) site(s) visité(s) : voir les rapports préventifs.")
    if d["visits_note"]:
        lines.append(d["visits_note"])
    _set(note, _cut(" ".join(lines), 150))


def _achievements(slide, d):
    kpis, actions = d["done_kpis"][:4], d["done_actions"][:5]
    _set(_shape(slide, "Text 0"), "Ce que nous avons réalisé sur la période")
    cards = [("Carte réalisation 1", "Text 2", "Text 3"), ("Carte réalisation 2", "Text 5", "Text 6"),
             ("Carte réalisation 3", "Text 8", "Text 9"), ("Carte réalisation 4", "Text 11", "Text 12")]
    for i, names in enumerate(cards):
        shapes = [_shape(slide, n) for n in names]
        if i >= len(kpis):
            _remove(*shapes)
            continue
        _set(shapes[1], _cut(kpis[i]["value"], 8))
        _set(shapes[2], _cut(kpis[i]["label"], 50))
    for i in range(5):
        shapes = [_shape(slide, f"Pastille {i + 1}"), _shape(slide, f"Image {i}"), _shape(slide, f"Text {14 + 2 * i}")]
        if i >= len(actions):
            _remove(*shapes)
            continue
        _set(shapes[2], _cut(actions[i], 120))


def _recommendations(slide, d):
    recos = d["recommendations"][:5]
    _set(_shape(slide, "Text 0"), f"{NUMBERS.get(len(recos), len(recos))} recommandation"
                                  f"{'s' if len(recos) > 1 else ''}, priorisée{'s' if len(recos) > 1 else ''} "
                                  "par impact et effort")
    quadrant = {(imp, eff): _shape(slide, f"Quadrant {imp} {eff}")
                for imp in ("high", "medium") for eff in ("low", "medium", "high")}
    markers = [_shape(slide, f"Repère {k}") for k in range(1, 6)]
    marker_texts = [_same_box(slide, m) for m in markers]
    used = {}
    for k in range(5):
        num = _shape(slide, f"Numéro {k + 1}")
        num_text = _same_box(slide, num)
        title = _shape(slide, f"Text {26 + 4 * k}")
        why = _shape(slide, f"Text {27 + 4 * k}")
        if k >= len(recos):
            _remove(num, num_text, title, why, markers[k], marker_texts[k])
            continue
        r = recos[k]
        _set(title, _cut(r["title"], 45))
        _set(why, _cut(r["why"], 90))
        impact = "high" if (r["impact"] or "").strip().lower().startswith(("é", "e", "h", "fort")) else "medium"
        e = (r["effort"] or "").strip().lower()
        effort = "low" if e.startswith("faib") else ("high" if e.startswith(("é", "e", "h", "fort")) else "medium")
        q = quadrant[(impact, effort)]
        slot = used.get((impact, effort), 0)
        used[(impact, effort)] = slot + 1
        col, row = slot % 2, slot // 2
        left = q.left + Inches(0.25) + Inches(0.62) * col
        top = q.top + Inches(1.0) + Inches(0.62) * row - (Inches(0.5) if slot >= 2 else 0)
        for sh in (markers[k], marker_texts[k]):
            sh.left, sh.top = Emu(int(left)), Emu(int(top))


def _roadmap(slide, d):
    end = d["end"]
    first = datetime.date(end.year + (end.month == 12), end.month % 12 + 1, 1)
    months = []
    m = first
    for _i in range(4):
        months.append(m)
        m = datetime.date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    window_end = m  # 1er jour du 5e mois
    headers = [("Mois Nov. 2026", "Text 2"), ("Mois Déc. 2026", "Text 4"), ("Mois Janv. 2027", "Text 6"),
               ("Mois Févr. 2027", "Text 8")]
    col0 = _shape(slide, headers[0][0])
    x0, col_w = col0.left, col0.width
    for (box, text), month in zip(headers, months):
        _set(_shape(slide, text), f"{MONTHS_SHORT[month.month - 1]} {month.year}")

    def xpos(day):
        span = (window_end - first).days
        frac = max(0.0, min(1.0, (day - first).days / span))
        return x0 + int(col_w * 4 * frac)

    proto_row = [_shape(slide, "Ligne Sécurité"), _shape(slide, "Ligne Infrastructure")]
    proto_label = _shape(slide, "Text 10")
    proto_bar = _shape(slide, "Tâche Inventaire des certificats")
    proto_in = _shape(slide, "Text 14")
    proto_out = _shape(slide, "Text 12")
    keep = {sh.name for sh in slide.shapes if sh.name.startswith("Mois") or sh.name in
            ("Text 0", "Text 2", "Text 4", "Text 6", "Text 8") or sh.name.startswith("Slide Number")}
    protos = [copy.deepcopy(s._element) for s in (*proto_row, proto_label, proto_bar, proto_in, proto_out)]
    for sh in list(slide.shapes):
        if sh.name not in keep:
            _remove(sh)
    tree = slide.shapes._spTree

    def add(proto_el, left, top, width=None, height=None):
        el = copy.deepcopy(proto_el)
        el.xpath("./*[1]/p:cNvPr")[0].set("id", str(_next_id(slide)))
        tree.append(el)
        sh = slide.shapes[-1]
        sh.left, sh.top = Emu(int(left)), Emu(int(top))
        if width is not None:
            sh.width = Emu(int(width))
        if height is not None:
            sh.height = Emu(int(height))
        return sh

    groups = {}
    for a in d["action_plan"]:
        due = _date(a.get("due"))
        if due:
            groups.setdefault(_cut(a.get("owner") or "À désigner", 22), []).append((due, a))
    y = Inches(2.10)
    bottom = Inches(6.75)
    for gi, (owner, items) in enumerate(groups.items()):
        items.sort(key=lambda x: x[0])
        height = Inches(0.12) + Inches(0.40) * len(items)
        if y + height > bottom:
            break
        add(protos[gi % 2], proto_row[0].left, y, proto_row[0].width, height)
        lab = add(protos[2], proto_label.left, y, None, height)
        _set(lab, owner)
        for k, (due, a) in enumerate(items):
            top = y + Inches(0.06) + Inches(0.40) * k
            start_day = max(first, due - datetime.timedelta(days=30))
            left = xpos(start_day)
            width = max(Inches(0.3), xpos(due) - left)
            bar = add(protos[3], left, top, width)
            _fill(bar, MSO_THEME_COLOR.ACCENT_1 if (a.get("priority") or "").lower().startswith("haut")
                  else MSO_THEME_COLOR.ACCENT_2)
            label = _cut(a["action"], 48)
            if width >= Inches(2.3):
                txt = add(protos[4], left + Inches(0.08), top, width - Inches(0.1))
            else:
                txt = add(protos[5], left + width + Inches(0.1), top, Inches(3.2))
                if left + width + Inches(3.3) > Inches(12.73):
                    txt.left = Emu(int(max(x0, left - Inches(3.3))))
            _set(txt, label)
        y += height + Inches(0.08)
    return bool(groups)


def _action_plan(slide, d):
    table_shape = _shape(slide, "Table 0")
    tbl = table_shape.table._tbl
    rows = tbl.tr_lst
    proto = copy.deepcopy(rows[1])
    for tr in rows[1:]:
        tbl.remove(tr)
    items = d["action_plan"]
    shown = items[:9]
    for a in shown:
        tr = copy.deepcopy(proto)
        tbl.append(tr)
        values = [_cut(a.get("action"), 90), a.get("priority") or "—", _cut(a.get("owner"), 30) or "—",
                  a.get("due") or "—", a.get("status") or "—"]
        for tc, value in zip(tr.tc_lst, values):
            ts = tc.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/main}t")
            ts[0].text = str(value)
            for extra in ts[1:]:
                extra.text = ""
    if len(items) > len(shown):
        tr = copy.deepcopy(proto)
        tbl.append(tr)
        for i, tc in enumerate(tr.tc_lst):
            ts = tc.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/main}t")
            ts[0].text = f"… et {len(items) - len(shown)} autre(s) action(s)" if i == 0 else ""
    n = len(items)
    _set(_shape(slide, "Text 0"), "Plan d'action et responsabilités" if n else "Plan d'action")


def _decisions(slide, d):
    decisions = d["decisions"][:3]
    n = len(decisions)
    _set(_shape(slide, "Text 0"), f"{NUMBERS.get(n, n)} décision{'s' if n > 1 else ''} "
                                  f"attendue{'s' if n > 1 else ''} du comité de direction")
    cards = [("Carte décision 1", "Numéro décision 1", "Text 3", "Text 4", "Text 5"),
             ("Carte décision 2", "Numéro décision 2", "Text 8", "Text 9", "Text 10"),
             ("Carte décision 3", "Numéro décision 3", "Text 13", "Text 14", "Text 15")]
    for i, names in enumerate(cards):
        shapes = [_shape(slide, x) for x in names]
        if i >= n:
            _remove(*shapes)
            continue
        _set(shapes[3], _cut(decisions[i]["title"], 60))
        _set(shapes[4], _cut(decisions[i]["detail"], 140))
    _set(_shape(slide, "Text 16"), _cut(d["next_point"], 120) if d["next_point"]
         else "Prochain point : à fixer avec le comité de direction.")


def _notes(d):
    """Notes de l'orateur, à la place de celles de l'exemple du modèle."""
    t, r = d["tickets_total"], d["tickets_resolved"]
    period = f"du {d['start']:%d/%m/%Y} au {d['end']:%d/%m/%Y}"
    sources = ", ".join(d["quarterly_reports"]) or "aucun rapport trimestriel validé sur la période"
    return [
        f"Bilan {period} pour {d['end_client']} ({d['esn']}). Saisies reprises de : {sources}.",
        f"Message clé : {d['headline']}. Résolution dans les délais : {fmt_pct(d['resolution_pct'])} "
        f"pour un objectif de {fmt_pct(d['resolution_target'])}.",
        f"{r} tickets résolus sur {t} ; {d['tickets_open']} encore ouverts.",
        "Engagements de délai calculés sur les tickets de la période ; disponibilité reprise des rapports "
        "trimestriels.",
        "Causes issues des rapports curatifs validés ; équipements cités dans les tickets.",
        f"{d['visits_done']} visite(s) préventive(s) validée(s) sur la période.",
        "Réalisations reprises des rapports trimestriels.",
        "Recommandations reprises des rapports trimestriels, placées selon leur impact et leur effort.",
        "Feuille de route dérivée du plan d'action (échéances).",
        f"{len(d['action_plan'])} action(s) au plan.",
        "Décisions attendues reprises des rapports trimestriels.",
    ]


# --- Assemblage -------------------------------------------------------------------------------------

def build_comex(d):
    """Renvoie le fichier PowerPoint (octets) du COMEX décrit par `d` (voir data.comex_data)."""
    prs = Presentation(str(TEMPLATE))
    s = list(prs.slides)
    _cover(s[0], d)
    _synthesis(s[1], d)
    _tickets(s[2], d)
    _commitments(s[3], d)
    _incidents(s[4], d)
    _preventive(s[5], d)
    drop = []
    if d["done_kpis"] or d["done_actions"]:
        _achievements(s[6], d)
    else:
        drop.append(s[6])
    if d["recommendations"]:
        _recommendations(s[7], d)
    else:
        drop.append(s[7])
    if not _roadmap(s[8], d):
        drop.append(s[8])
    if d["action_plan"]:
        _action_plan(s[9], d)
    else:
        drop.append(s[9])
    if d["decisions"]:
        _decisions(s[10], d)
    else:
        drop.append(s[10])
    for slide, text in zip(s, _notes(d)):
        if slide.has_notes_slide:
            slide.notes_slide.notes_text_frame.text = text
    for slide in drop:
        _drop_slide(prs, slide)
    for slide in prs.slides:
        _unique_ids(slide)
    prs.core_properties.title = f"COMEX — {d['end_client']} — {d['start']:%d/%m/%Y} au {d['end']:%d/%m/%Y}"
    prs.core_properties.author = "Aptitude Support"
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()
