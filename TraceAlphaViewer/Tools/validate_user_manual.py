"""Controle les liens hors connexion, les captures et les livrables du manuel."""
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import struct

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / 'docs' / 'manuel-utilisateur'


class ManualParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.links = []
        self.figures = 0
        self.sections = 0
        self.images = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get('id'):
            self.ids.append(attributes['id'])
        for key in ('href', 'src'):
            if attributes.get(key):
                self.links.append(attributes[key])
        if tag == 'figure':
            self.figures += 1
        if tag == 'section':
            self.sections += 1
        if tag == 'image':
            self.images.append(attributes)
        if tag == 'svg' and attributes.get('role') == 'img':
            assert attributes.get('aria-label'), 'Illustration sans description accessible'


def main():
    html = (DIRECTORY / 'index.html').read_text(encoding='utf-8')
    parser = ManualParser()
    parser.feed(html)
    assert len(parser.ids) == len(set(parser.ids)), 'Ancres dupliquees'
    assert parser.sections == 22, 'Un chapitre du manuel manque'
    assert parser.figures >= 13, 'Illustrations manquantes'
    for link in parser.links:
        if link.startswith('#'):
            assert link[1:] in parser.ids, f'Ancre absente : {link}'
        else:
            assert not re.match(r'\w+://|//|data:', link), f'Ressource externe : {link}'
            path = (DIRECTORY / link).resolve()
            assert path.is_relative_to(DIRECTORY.resolve()), f'Lien hors du manuel : {link}'
            assert path.is_file(), f'Fichier absent : {link}'
    assert not re.search(r'@import|https?://|url\(', html), 'Dependance externe dans le guide'
    metadata = json.loads((DIRECTORY / 'assets' / 'captures.json').read_text(encoding='utf-8'))
    assert len(metadata) == 13, 'Treize captures sont attendues'
    for name, size in metadata.items():
        data = (DIRECTORY / 'assets' / f'{name}.png').read_bytes()
        assert data[:8] == b'\x89PNG\r\n\x1a\n', f'PNG invalide : {name}'
        assert struct.unpack('>II', data[16:24]) == (size['width'], size['height']), name
    for image in parser.images:
        size = metadata[Path(image['href']).stem]
        assert int(image['width']) == size['width'] and int(image['height']) == size['height']
    pdf = (DIRECTORY / 'Bien-demarrer-avec-TraceAlphaViewer.pdf').read_bytes()
    assert pdf.startswith(b'%PDF-') and pdf.rstrip().endswith(b'%%EOF'), 'PDF incomplet'
    pages = len(re.findall(rb'/Type\s*/Page\b', pdf))
    assert pages == 22, f'Pagination inattendue : {pages} pages, controle visuel requis'
    assert b'/Subtype /Link' in pdf, 'Les liens du PDF sont absents'
    print(f'Manuel utilisateur : {parser.sections} sections, 13 captures, {pages} pages PDF, liens locaux valides')


if __name__ == '__main__':
    main()
