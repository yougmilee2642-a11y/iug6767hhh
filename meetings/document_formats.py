"""Bounded stdlib readers for tables, presentations and mail. No formulas/macros execute."""
import csv
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
import io
from pathlib import PurePosixPath
import re
import posixpath
import zipfile
from xml.etree import ElementTree as ET

MAX_UNZIPPED = 20 * 1024 * 1024
S = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'


class FormatError(ValueError):
    pass


def decoded(data):
    for encoding in ('utf-8-sig', 'cp1251'):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise FormatError('Не удалось определить кодировку документа.')


def xml(archive, name):
    raw = archive.read(name)
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise FormatError('Объявления DTD/ENTITY в документе не поддерживаются.')
    return ET.fromstring(raw)


def archive_for(data):
    archive = zipfile.ZipFile(io.BytesIO(data))
    if sum(i.file_size for i in archive.infolist()) > MAX_UNZIPPED or len(archive.infolist()) > 5000:
        raise FormatError('Документ слишком большой после распаковки.')
    if any(PurePosixPath(i.filename).is_absolute() or '..' in PurePosixPath(i.filename).parts
           or '\\' in i.filename for i in archive.infolist()):
        raise FormatError('Недопустимые пути в архиве документа.')
    return archive


class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag in ('p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3') and not self.hidden:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def html_text(text):
    reader = TextHTML()
    reader.feed(text)
    return ''.join(reader.parts)


def read_blocks(kind, data):
    if kind == 'csv':
        text = decoded(data)
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=',;\t')
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(io.StringIO(text), dialect))
        if not rows:
            return []
        headers = rows[0]
        return [(f'строка {number}', '; '.join(f'{headers[i] if i < len(headers) else i + 1}: {value}'
                for i, value in enumerate(row))) for number, row in enumerate(rows[1:], 2) if any(row)]
    if kind == 'xlsx':
        with archive_for(data) as archive:
            shared = []
            if 'xl/sharedStrings.xml' in archive.namelist():
                shared = [''.join(t.text or '' for t in node.iter(S + 't'))
                          for node in xml(archive, 'xl/sharedStrings.xml').iter(S + 'si')]
            sheets = []
            if 'xl/workbook.xml' in archive.namelist() and 'xl/_rels/workbook.xml.rels' in archive.namelist():
                relations = {}
                for relation in xml(archive, 'xl/_rels/workbook.xml.rels'):
                    if relation.get('TargetMode') == 'External':
                        continue
                    target = relation.get('Target', '')
                    path = posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/' + target)
                    if not path.startswith('xl/worksheets/') or '..' in PurePosixPath(path).parts:
                        continue
                    relations[relation.get('Id')] = path
                rid = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
                for sheet in xml(archive, 'xl/workbook.xml').iter(S + 'sheet'):
                    path = relations.get(sheet.get(rid))
                    if path is None:
                        raise FormatError('Не удалось сопоставить имя листа с его содержимым.')
                    sheets.append((sheet.get('name', ''), path))
            else:
                raise FormatError('В XLSX нет структуры книги или связей листов.')
            output = []
            for title, path in sheets:
                headers = None
                for row in xml(archive, path).iter(S + 'row'):
                    cells = []
                    for cell in row.findall(S + 'c'):
                        value = cell.find(S + 'v')
                        formula = cell.find(S + 'f')
                        if formula is not None:
                            text = '[формула, не вычислялась] ' + (formula.text or '')
                        elif cell.get('t') == 'inlineStr':
                            text = ''.join(t.text or '' for t in cell.iter(S + 't'))
                        elif cell.get('t') == 's' and value is not None:
                            shared_index = int(value.text)
                            if not 0 <= shared_index < len(shared):
                                raise FormatError('Некорректный индекс строки XLSX.')
                            text = shared[shared_index]
                        else:
                            text = value.text if value is not None and value.text else ''
                        cells.append((cell.get('r', ''), text))
                    if not cells:
                        continue
                    if headers is None:
                        headers = {re.sub(r'\d+', '', ref): text for ref, text in cells}
                        continue
                    output.append((title + '!' + cells[0][0] + ':' + cells[-1][0],
                                   '; '.join(headers.get(re.sub(r'\d+', '', ref), ref) + ': ' + text for ref, text in cells)))
            return output
    if kind == 'pptx':
        with archive_for(data) as archive:
            paths = sorted((n for n in archive.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', n)),
                           key=lambda n: int(re.search(r'(\d+)\.xml$', n)[1]))
            return [(f'слайд {number}', '\n'.join(''.join(n.text or '' for n in p.iter(A + 't'))
                     for p in xml(archive, path).iter(A + 'p'))) for number, path in enumerate(paths, 1)]
    if kind == 'eml':
        message = BytesParser(policy=policy.default).parsebytes(data)
        body = message.get_body(preferencelist=('plain', 'html')) if message.is_multipart() else message
        content = body.get_content() if body else ''
        if not isinstance(content, str):
            raise FormatError('В письме нет текстового тела.')
        if body and body.get_content_type() == 'text/html':
            content = html_text(content)
        return [('письмо, тема и тело', str(message.get('Subject', '')) + '\n' + content)]
    text = decoded(data)
    if kind == 'html':
        text = html_text(text)
    return [(f'абз. {i}', part) for i, part in enumerate(re.split(r'\n\s*\n', text), 1)]


def fragments(kind, data):
    try:
        blocks = read_blocks(kind, data)
    except FormatError:
        raise
    except (ValueError, KeyError, IndexError, zipfile.BadZipFile, ET.ParseError, RuntimeError, EOFError, csv.Error):
        raise FormatError('Файл повреждён или не соответствует заявленному формату.') from None
    result = []
    for location, raw in blocks:
        text = raw.replace('\x00', '').strip()
        if not text:
            continue
        # Never cut a table row/condition in half: retain its headers and negation.
        if len(text) > 20000:
            raise FormatError('Фрагмент превышает 20000 символов; разделите документ на абзацы или строки.')
        result.append({'idx': len(result) + 1, 'location': location, 'text': text})
    if not result:
        raise FormatError('В документе нет читаемого текстового содержимого.')
    return result
