import sqlite3, os, sys

DB = os.environ.get('DATABASE_PATH', 'data/db/market.db')
conn = sqlite3.connect(DB)

before = conn.execute('SELECT COUNT(*) FROM price_history').fetchone()[0]

to_delete = conn.execute(
    'SELECT COUNT(*) FROM ('
    '    SELECT id, ROW_NUMBER() OVER (PARTITION BY uuid ORDER BY fetched_at ASC) AS rn'
    '    FROM price_history'
    ') WHERE rn % 3 != 1'
).fetchone()[0]

print(f'Total rows:    {before:,}')
print(f'Would delete:  {to_delete:,}')
print(f'Would keep:    {before - to_delete:,}')

if '--execute' not in sys.argv:
    print('\nDry run. Pass --execute to actually delete.')
    conn.close()
    sys.exit(0)

conn.execute(
    'DELETE FROM price_history WHERE id IN ('
    '    SELECT id FROM ('
    '        SELECT id, ROW_NUMBER() OVER (PARTITION BY uuid ORDER BY fetched_at ASC) AS rn'
    '        FROM price_history'
    '    ) WHERE rn % 3 != 1'
    ')'
)
conn.commit()

after = conn.execute('SELECT COUNT(*) FROM price_history').fetchone()[0]
conn.execute('PRAGMA wal_checkpoint(FULL)')
conn.execute('PRAGMA incremental_vacuum')
conn.commit()
conn.close()

print(f'\nDeleted {before - after:,} rows. Remaining: {after:,}')
