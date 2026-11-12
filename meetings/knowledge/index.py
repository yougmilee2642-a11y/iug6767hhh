"""Request-scoped FTS5: even BM25 corpus statistics contain only authorized data.

This prototype rebuilds a TEMP index for a request, then drops it. It trades
large-corpus speed for strict isolation of ranking statistics and immediate ACL
revocation without cached permission snapshots. No extensions are loaded.
"""
import sqlite3

from meetings.access import predicate
from meetings.auth import MeetError
from meetings.knowledge.language import lexeme, terms
from meetings.textutil import words


def visible_fragments(c, actor, *, meeting_id=None, model=False):
    visible, params = predicate(c, actor, 'document', 'd', model=model)
    sql = ('SELECT f.*,d.title,d.created_at,d.filename FROM fragments f '
           'JOIN documents d ON d.id=f.document_id WHERE ' + visible)
    if meeting_id is not None:
        sql += ' AND EXISTS (SELECT 1 FROM meeting_documents md WHERE md.document_id=d.id AND md.meeting_id=?)'
        params.append(meeting_id)
    return [dict(row) for row in c.execute(sql + ' ORDER BY f.id', params)]


def normalized(text):
    return ' '.join(lexeme(word) for word in words(text))


def ranked(c, rows, question, *, require_all=False):
    """Rows must already be SQL-authorized and, for QA, eligible evidence.

    Every query term is quoted and comes from the lexical normalizer: FTS
    operators, column names and user syntax cannot become a MATCH expression.
    Only a server-owned table name is used as SQL syntax.
    """
    query = sorted(terms(question))
    if not query or not rows: return []
    expression = (' AND ' if require_all else ' OR ').join('"' + word + '"' for word in query)
    c.execute('CREATE VIRTUAL TABLE temp.focus_search USING fts5(body,tokenize="unicode61")')
    try:
        by_id = {row['id']: row for row in rows}
        c.executemany('INSERT INTO temp.focus_search(rowid,body) VALUES (?,?)',
                      [(row['id'], normalized(row['text'])) for row in rows])
        ordered = c.execute('SELECT rowid,bm25(focus_search) AS rank FROM temp.focus_search '
                            'WHERE focus_search MATCH ? ORDER BY rank,rowid', (expression,)).fetchall()
        return [by_id[row[0]] for row in ordered]
    finally:
        c.execute('DROP TABLE temp.focus_search')


def unavailable(user_id=None):
    return MeetError(503, 'search_unavailable', 'Поиск по документам недоступен. Данные сохранены; повторите запрос позже.',
                     audit={'user_id':user_id,'action':'search_unavailable','object_type':'search',
                            'result':'failed','error_code':'search_unavailable'})


def search(c, actor, question, limit=50):
    try:
        # Assistant search is a content projection. Secret files remain available
        # only through the explicit owner file path, never search snippets.
        return ranked(c, visible_fragments(c, actor, model=True), question, require_all=True)[:limit]
    except sqlite3.Error:
        raise unavailable(actor) from None
