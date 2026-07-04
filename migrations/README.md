# Migrations

SQL migration files applied in sequence to the SQLite database.

## Naming convention

```
001_description.sql
002_description.sql
```

Files run in alphabetical order, so the numeric prefix controls execution order.

## How they run

The CI workflow on the desktop self-hosted runner applies all `.sql` files in
this directory automatically on every push. No desktop visit required.

## Running manually on the desktop

```bash
for f in $(ls migrations/*.sql | sort); do
  echo "Applying $f"
  sqlite3 "$DB_PATH" < "$f"
done
```
