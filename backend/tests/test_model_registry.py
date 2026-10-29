"""Alembic must see webhook dedupe metadata without application imports."""
import subprocess
import sys


def test_alembic_base_registers_processed_events_and_retention_index():
    result = subprocess.run(
        [sys.executable, "-c", (
            "from app.db.base import Base; "
            "table = Base.metadata.tables['processed_webhook_events']; "
            "assert any(index.name == 'ix_processed_webhook_events_received_at' "
            "and [column.name for column in index.columns] == ['received_at'] "
            "for index in table.indexes)"
        )],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
