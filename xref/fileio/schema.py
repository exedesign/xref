USER_VERSION = 4
APPLICATION_ID = 2060242126


SCHEMA = [
    """
    CREATE TABLE items (
        id INTEGER PRIMARY KEY,
        type TEXT NOT NULL,
        x REAL DEFAULT 0,
        y REAL DEFAULT 0,
        z REAL DEFAULT 0,
        scale REAL DEFAULT 1,
        rotation REAL DEFAULT 0,
        flip INTEGER DEFAULT 1,
        data JSON
    )
    """,
    """
    CREATE TABLE sqlar (
        name TEXT PRIMARY KEY,
        item_id INTEGER NOT NULL UNIQUE,
        mode INT,
        mtime INT default current_timestamp,
        sz INT,
        data BLOB,
        FOREIGN KEY (item_id)
          REFERENCES items (id)
             ON DELETE CASCADE
             ON UPDATE NO ACTION
    )
    """,
    """
    CREATE TABLE meta (
        key TEXT PRIMARY KEY,
        value BLOB
    )
    """,
]


MIGRATIONS = {
    2: [
        "ALTER TABLE items ADD COLUMN data JSON",
        "UPDATE items SET data = json_object('filename', filename)",
    ],
    3: [
        """
        CREATE TABLE links (
            id INTEGER PRIMARY KEY,
            source_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            UNIQUE (source_id, target_id),
            FOREIGN KEY (source_id)
              REFERENCES items (id)
                 ON DELETE CASCADE
                 ON UPDATE NO ACTION,
            FOREIGN KEY (target_id)
              REFERENCES items (id)
                 ON DELETE CASCADE
                 ON UPDATE NO ACTION
        )
        """,
    ],
    4: [
        """
        CREATE TABLE meta (
            key TEXT PRIMARY KEY,
            value BLOB
        )
        """,
    ],
}
