"""
database.py
Obsługa bazy danych SQLite dla systemu rezerwacji korepetycji.

Struktura:
- uczniowie: dane ucznia + saldo godzin w pakiecie
- lekcje: zaplanowane/odbyte lekcje, powiązane z uczniem
"""

import sqlite3
from datetime import datetime

DB_NAME = "korepetycje.db"


def get_connection():
    """Zwraca połączenie z bazą danych."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row  # pozwala odwoływać się do kolumn po nazwie
    return conn


def init_db():
    """Tworzy tabele, jeśli jeszcze nie istnieją. Wywołaj raz na start aplikacji."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS uczniowie (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            imie TEXT NOT NULL,
            nazwisko TEXT,
            telefon TEXT,
            pakiet_godzin REAL NOT NULL DEFAULT 0,
            utworzono TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lekcje (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uczen_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            godzina TEXT NOT NULL,
            czas_trwania REAL NOT NULL DEFAULT 1.0,
            status TEXT NOT NULL DEFAULT 'zaplanowana',
            notatka TEXT,
            utworzono TEXT NOT NULL,
            FOREIGN KEY (uczen_id) REFERENCES uczniowie (id)
        )
    """)

    conn.commit()
    conn.close()


# --- UCZNIOWIE ---

def add_student(imie, nazwisko, telefon, pakiet_godzin):
    """Dodaje nowego ucznia. Zwraca id nowo utworzonego rekordu."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO uczniowie (imie, nazwisko, telefon, pakiet_godzin, utworzono)
           VALUES (?, ?, ?, ?, ?)""",
        (imie, nazwisko, telefon, pakiet_godzin, datetime.now().isoformat())
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id


def get_students():
    """Zwraca listę wszystkich uczniów jako listę słowników."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM uczniowie ORDER BY imie")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_student_by_id(uczen_id):
    """Zwraca dane jednego ucznia."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM uczniowie WHERE id = ?", (uczen_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def update_student_hours(uczen_id, nowa_liczba_godzin):
    """Ustawia nowe saldo godzin dla ucznia (np. po doładowaniu pakietu)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE uczniowie SET pakiet_godzin = ? WHERE id = ?",
        (nowa_liczba_godzin, uczen_id)
    )
    conn.commit()
    conn.close()

def delete_student(uczen_id):
    """Usuwa ucznia oraz wszystkie powiązane z nim lekcje."""
    conn = get_connection()
    cursor = conn.cursor()
    # Najpierw usuwamy lekcje ucznia (żeby nie zostały "osierocone" w bazie)
    cursor.execute("DELETE FROM lekcje WHERE uczen_id = ?", (uczen_id,))
    cursor.execute("DELETE FROM uczniowie WHERE id = ?", (uczen_id,))
    conn.commit()
    conn.close()
def update_student(uczen_id, imie, nazwisko, telefon, pakiet_godzin):
    """Aktualizuje dane ucznia."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE uczniowie 
           SET imie = ?, nazwisko = ?, telefon = ?, pakiet_godzin = ?
           WHERE id = ?""",
        (imie, nazwisko, telefon, pakiet_godzin, uczen_id)
    )
    conn.commit()
    conn.close()

def adjust_student_hours(uczen_id, delta):
    """Zmienia saldo godzin ucznia o wartość delta (dodatnia lub ujemna)."""
    student = get_student_by_id(uczen_id)
    if student is None:
        raise ValueError(f"Nie znaleziono ucznia o id={uczen_id}")
    nowe_saldo = student["pakiet_godzin"] + delta
    update_student_hours(uczen_id, nowe_saldo)
    return nowe_saldo


# --- LEKCJE ---

def add_lesson(uczen_id, data, godzina, czas_trwania=1.0, notatka=""):
    """
    Dodaje nową lekcję i automatycznie odejmuje godziny z pakietu ucznia.
    data: string w formacie 'YYYY-MM-DD'
    godzina: string w formacie 'HH:MM'
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO lekcje (uczen_id, data, godzina, czas_trwania, status, notatka, utworzono)
           VALUES (?, ?, ?, ?, 'zaplanowana', ?, ?)""",
        (uczen_id, data, godzina, czas_trwania, notatka, datetime.now().isoformat())
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()

    # Odejmij godziny z pakietu ucznia
    adjust_student_hours(uczen_id, -czas_trwania)

    return new_id


def get_upcoming_lessons():
    """Zwraca listę lekcji posortowaną po dacie i godzinie, z imieniem ucznia."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT lekcje.*, uczniowie.imie, uczniowie.nazwisko
        FROM lekcje
        JOIN uczniowie ON lekcje.uczen_id = uczniowie.id
        WHERE lekcje.status = 'zaplanowana'
        ORDER BY lekcje.data ASC, lekcje.godzina ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_lessons_by_date_range(data_od, data_do):
    """Zwraca lekcje (wszystkie statusy) mieszczące się w podanym zakresie dat."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT lekcje.*, uczniowie.imie, uczniowie.nazwisko
        FROM lekcje
        JOIN uczniowie ON lekcje.uczen_id = uczniowie.id
        WHERE lekcje.data BETWEEN ? AND ?
        ORDER BY lekcje.data ASC, lekcje.godzina ASC
    """, (data_od, data_do))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def mark_lesson_status(lekcja_id, status):
    """Zmienia status lekcji, np. na 'odbyta' lub 'odwolana'."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE lekcje SET status = ? WHERE id = ?", (status, lekcja_id))
    conn.commit()
    conn.close()


def cancel_lesson(lekcja_id):
    """Odwołuje lekcję i zwraca godziny do pakietu ucznia."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM lekcje WHERE id = ?", (lekcja_id,))
    lekcja = cursor.fetchone()
    conn.close()

    if lekcja is None:
        raise ValueError(f"Nie znaleziono lekcji o id={lekcja_id}")

    mark_lesson_status(lekcja_id, "odwolana")
    adjust_student_hours(lekcja["uczen_id"], lekcja["czas_trwania"])
    
