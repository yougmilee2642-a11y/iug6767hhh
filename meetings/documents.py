"""TXT / DOCX / text-PDF parsing into stable, citable fragments. Content is data, never executed."""
import io
import re
import zipfile
from xml.etree import ElementTree

MAX_BYTES = 5 * 1024 * 1024
MAX_UNZIPPED = 30 * 1024 * 1024
FRAGMENT_CHARS = 700
SHORT = 120
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


class DocumentError(ValueError):
    pass


def kind_of(filename: str) -> str:
    extension = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if extension not in ('txt', 'docx', 'pdf', 'xlsx', 'csv', 'pptx', 'md', 'html', 'eml'):
        raise DocumentError('Поддерживаются TXT, DOCX, текстовый PDF, XLSX, CSV, PPTX, MD, HTML и EML.')
    return extension


def _txt(data: bytes) -> list[tuple[int | None, str]]:
    for encoding in ('utf-8-sig', 'cp1251'):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise DocumentError('Не удалось определить кодировку TXT (ожидается UTF-8 или Windows-1251).')
    return [(None, p) for p in re.split(r'\n\s*\n|\r\n\s*\r\n', text)]


def _docx(data: bytes) -> list[tuple[int | None, str]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        info = archive.getinfo('word/document.xml')
        if sum(i.file_size for i in archive.infolist()) > MAX_UNZIPPED:
            raise DocumentError('DOCX слишком большой после распаковки.')
        root = ElementTree.fromstring(archive.read(info))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, NotImplementedError, RuntimeError, ValueError, EOFError):
        raise DocumentError('Файл DOCX повреждён или не является документом Word.') from None
    paragraphs = []
    for paragraph in root.iter(W + 'p'):
        text = ''.join(node.text or '' for node in paragraph.iter() if node.tag in (W + 't', W + 'tab'))
        paragraphs.append((None, text))
    return paragraphs


def _pdf(data: bytes) -> list[tuple[int | None, str]]:
    output = []
    try:
        import pymupdf
        with pymupdf.open(stream=data, filetype='pdf') as document:
            for number, page in enumerate(document, 1):
                # Text blocks ≈ paragraphs; line wraps inside a block are joined.
                for block in page.get_text('blocks'):
                    if block[6] == 0:
                        output.append((number, re.sub(r'\s*\n\s*', ' ', block[4])))
    except ImportError:
        try:
            from pypdf import PdfReader
            for number, page in enumerate(PdfReader(io.BytesIO(data)).pages, 1):
                output += [(number, p) for p in re.split(r'\n\s*\n', page.extract_text() or '')]
        except Exception:
            raise DocumentError('Не удалось прочитать PDF.') from None
    except Exception:
        raise DocumentError('Не удалось прочитать PDF.') from None
    if not any(text.strip() for _, text in output):
        raise DocumentError('В PDF нет текстового слоя (скан). Распознавание сканов в MVP не поддерживается.')
    return output


def fragments(filename: str, data: bytes) -> tuple[str, list[dict]]:
    if len(data) > MAX_BYTES:
        raise DocumentError('Файл больше 5 МБ.')
    kind = kind_of(filename)
    if kind in ('docx', 'xlsx', 'pptx') and not data.startswith(b'PK\x03\x04'):
        raise DocumentError('Сигнатура файла не соответствует офисному документу.')
    if kind == 'pdf' and not data.startswith(b'%PDF-'):
        raise DocumentError('Сигнатура файла не соответствует PDF.')
    if kind not in ('docx', 'xlsx', 'pptx', 'pdf') and (
            data.startswith((b'PK\x03\x04', b'%PDF-', b'\x89PNG', b'\xff\xd8\xff', b'GIF8', b'RIFF', b'MZ')) or b'\x00' in data):
        raise DocumentError('Бинарный файл не является текстовым документом.')
    if kind not in ('txt', 'docx', 'pdf'):
        from meetings.document_formats import fragments as read_structured, FormatError
        try:
            return kind, read_structured(kind, data)
        except FormatError as error:
            raise DocumentError(str(error)) from None
    blocks = {'txt': _txt, 'docx': _docx, 'pdf': _pdf}[kind](data)
    result, buffer, page, start, paragraph_no = [], [], None, 1, 0

    def flush():
        if buffer:
            text = '\n'.join(buffer).strip()
            where = f'стр. {page}, ' if page else ''
            span = f'абз. {start}' if paragraph_no == start else f'абз. {start}–{paragraph_no}'
            result.append({'location': f'{where}{span}', 'text': text})

    for block_page, raw in blocks:
        text = re.sub(r'[ \t]+', ' ', raw.replace('\x00', '').replace('\xad', '-')).strip()
        if not text:
            continue
        # One paragraph = one fragment for precise citations; only short headings get merged forward.
        if buffer and (block_page != page or len('\n'.join(buffer)) >= SHORT
                       or len('\n'.join(buffer)) + len(text) > FRAGMENT_CHARS):
            flush()
            buffer = []
        if not buffer:
            start = paragraph_no + 1
            page = block_page
        paragraph_no += 1
        # Very long paragraphs are split on sentence boundaries to keep citations precise.
        while len(text) > FRAGMENT_CHARS * 1.5:
            cut = text.rfind('. ', 0, FRAGMENT_CHARS) + 1
            if not cut:
                if len(text) > 20000:
                    raise DocumentError('Слишком длинный неделимый абзац; разделите документ.')
                break
            buffer.append(text[:cut].strip())
            flush()
            buffer, start = [], paragraph_no
            text = text[cut:].strip()
        buffer.append(text)
    flush()
    if not result:
        raise DocumentError('В документе не найден текст.')
    for index, fragment in enumerate(result, 1):
        fragment['idx'] = index
        fragment['location'] = f"{fragment['location']} (фрагмент {index})"
    return kind, result
