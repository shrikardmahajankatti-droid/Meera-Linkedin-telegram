from pathlib import Path

from bot import db
from bot.import_notes import import_notes


def test_insert_note_dedup(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)

    first = db.insert_note(db_path, source="telegram", source_id="42", text="hello")
    assert first is not None

    dupe = db.insert_note(db_path, source="telegram", source_id="42", text="hello again")
    assert dupe is None

    assert db.count_notes(db_path) == 1


def test_import_notes_idempotent(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)

    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    (notes_dir / "note1.txt").write_text("Customer said the serum stings for the first two uses.")
    (notes_dir / "note2.md").write_text("pH of new batch came back at 5.2, need to check spec.")
    (notes_dir / "ignored.jpg").write_text("not a note file")

    inserted, skipped = import_notes(db_path, notes_dir)
    assert inserted == 2
    assert skipped == 0
    assert db.count_notes(db_path) == 2

    inserted2, skipped2 = import_notes(db_path, notes_dir)
    assert inserted2 == 0
    assert skipped2 == 2
    assert db.count_notes(db_path) == 2


def test_import_notes_missing_dir(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    inserted, skipped = import_notes(db_path, tmp_path / "does-not-exist")
    assert inserted == 0
    assert skipped == 0
