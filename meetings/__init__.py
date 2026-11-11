"""CallWise Meetings: documents -> preparation -> transcript -> verified protocol -> confirmed tasks.

Everything is processed locally (SQLite + loopback Ollama). Content of documents and transcripts is
treated strictly as data: model output only fills draft fields that a human must confirm.
"""
