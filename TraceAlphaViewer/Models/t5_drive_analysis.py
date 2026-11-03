"""Chaînes T4/T5 non mesurées compatibles avec un défaut d'entraînement."""
import re

from Models.trace_calendar import observation_clock


_FINISH = re.compile(r'transfert T3->T4 termin.*?longueur=([\d.,]+) mm.*?idB=(\d+)', re.I)
_SUMMARY = re.compile(r'=> longueur boite .*?\(T4C\)=(-?\d+).*?\(T4T\)=(-?\d+)', re.I)
_CREATE = re.compile(r"BdD: Cr\S*ation de la boite '([^']*)' (.*?) x=.*?IdA:(\d+)", re.I)
_ADD = re.compile(r'AjoutBtT5\.idA(\d+)\.idB(\d+)', re.I)
_WIDTH = re.compile(r'largeur lue sur T5\s*<\s*2\s*mm.*?C9=([01])', re.I)
_MEASURE = re.compile(r'MAJ \(APRES-MESURE-LARG\).*?IdA:(\d+).*?nvlle lxH:(-?\d+)x(-?\d+)', re.I)
_REMOVE = re.compile(r'(?:supp\. de T5 la boite Id:|Suppr\. la boite IdA:|IdBdD:|-suppression de la boite ID:)(\d+)', re.I)
_RESTART = re.compile(r'version logiciel VBalpha:', re.I)


def analyze_t5_drive(lines, origin=None):
    """Un appel ne traite qu'un segment ; aucune identité ne traverse sa limite."""
    clock = observation_clock(lines, origin)
    pending = summary = transfer = active = None
    cycles, result = {}, []
    previous = None

    def proof(line, text, state, time, label):
        stamp = re.search(r'\d+\|\d{2}:\d{2}:\d{2}(?:\.\d+)?', text)
        return {'line': line, 'time': time,
                'time_str': clock.label(line, time, state.timestamp_str, stamp[0] if stamp else None),
                'label': label, 'detail': text.strip()}

    for (line, text, state), time in zip(lines, clock.values(lines)):
        lower = text.lower()
        restart = ('version logiciel vbalpha:' in lower or
                   (not text.isascii() and _RESTART.search(text)))
        if (previous is not None and (time - previous > 120 or time < previous - 2)) or restart:
            pending = summary = transfer = active = None
            cycles.clear()
        previous = time
        # Les ruptures temporelles restent traitees meme sans fait T4/T5.
        if text.isascii() and not ('t3->t4' in lower or 't5' in lower or
                '=> longueur boite' in lower or 'maj (apres-mesure-larg)' in lower or
                'bdd:' in lower or 'supp.' in lower or
                'suppr.' in lower or 'suppression de la boite' in lower):
            continue
        if 'demande le transfert de t3->t4' in lower:
            pending = None
        match = _FINISH.search(text) if 'transfert t3->t4 termin' in lower else None
        if match:
            pending = dict(proof(line, text, state, time, 'Longueur T4'),
                           id_b=int(match[2]), length_mm=float(match[1].replace(',', '.')))
        if 'demande le transfert (physique)' in lower and 't4 vers t5' in lower:
            active = summary = transfer = None
        if 'la boite est rendu (physiquement) sur t5' in lower:
            transfer = proof(line, text, state, time, 'Transfert T4 vers T5 confirmé')
        match = _SUMMARY.search(text) if '=> longueur boite' in lower else None
        if match:
            summary = dict(proof(line, text, state, time, 'Bilan T4C/T4T'),
                           t4c_mm=int(match[1]), t4t_mm=int(match[2]))
        match = _CREATE.search(text) if 'bdd:' in lower else None
        if match:
            active = int(match[3])
            cycles[active] = {'id_alpha': active, 'barcode': match[1], 'name': match[2],
                             'created': proof(line, text, state, time, 'Création T5'),
                             'transfer': transfer, 't4': summary, 'length': None,
                             'height': None, 'width': None, 'link': None}
            transfer = summary = None
        match = _ADD.search(text) if 'ajoutbtt5' in lower else None
        if match:
            ida, idb = map(int, match.groups())
            row = cycles.get(ida)
            if (row and pending and pending['id_b'] == idb
                    and row['transfer'] and pending['line'] < row['transfer']['line'] < row['created']['line'] < line):
                row['length'] = pending
                row['link'] = proof(line, text, state, time, 'Lien idB/IdA')
                row['id_b'] = idb
            else:
                cycles.pop(ida, None)
            pending = None
            active = ida if ida in cycles else None
        row = cycles.get(active)
        if row and row['link'] and "pas de boite sous le laser t5" in lower:
            row['height'] = proof(line, text, state, time, 'Absence sous le laser hauteur')
            row['width'] = None
        match = _WIDTH.search(text) if 'largeur lue sur t5' in lower else None
        if row and match and row['height'] and row['height']['line'] < line:
            row['width'] = dict(proof(line, text, state, time, 'Largeur finale invalide'), c9=int(match[1]))
        match = _MEASURE.search(text) if 'maj (apres-mesure-larg)' in lower else None
        if match and int(match[1]) in cycles:
            if int(match[2]) >= 2 and int(match[3]) > 2:
                del cycles[int(match[1])]
                if active == int(match[1]):
                    active = None
        if 'alpha:t5-list-pack' in lower:
            for part in text.replace(chr(182), '<Dc2>').split('@'):
                fields = part.split('<Dc2>')
                if fields[0] == '':
                    fields = fields[1:]
                if len(fields) < 23 or not fields[0].isdigit():
                    continue
                ida = int(fields[0])
                if ida in cycles and fields[4].isdigit() and fields[5].isdigit():
                    if int(fields[4]) >= 2 and int(fields[5]) > 2:
                        del cycles[ida]
                        if active == ida:
                            active = None
        match = _REMOVE.search(text) if any(token in lower for token in ('supp.', 'suppr.', 'suppression de la boite')) else None
        if match:
            ida = int(match[1])
            other_id = re.search(r'IdT5:(\d+)', text, re.I)
            if other_id and int(other_id[1]) != ida:
                cycles.pop(ida, None)
                if active == ida:
                    active = None
                continue
            row = cycles.pop(ida, None)
            if active == ida:
                active = None
            if row and all(row[key] for key in ('length', 'transfer', 'link', 'height', 'width')):
                if row['length']['length_mm'] > 0 and (not row['t4'] or row['t4']['t4c_mm'] > 0):
                    row['removed'] = proof(line, text, state, time, 'Suppression informatique')
                    result.append(row)
    return result
