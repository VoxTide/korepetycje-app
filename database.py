"""
database.py
Obsługa bazy danych SQLite dla systemu rezerwacji korepetycji.

Struktura:
- uzytkownicy: konta korepetytorów (login, zahaszowane hasło)
- uczniowie: dane ucznia + saldo godzin, powiązane z kontem korepetytora
- lekcje: zaplanowane/odbyte lekcje, powiązane z uczniem
"""

import sqlite3
import hashlib
import secrets
from datetime import datetime

DB_NAME = "korepetycje.db"


def get_connection():
    """Zwraca połączenie z bazą danych."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Tworzy tabele, jeśli jeszcze nie istnieją. Wywołaj raz na start aplikacji."""
    _napraw_przestarzala_tabele_uczniow()

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS uzytkownicy (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            login TEXT NOT NULL UNIQUE,
            hash_hasla TEXT NOT NULL,
            sol TEXT NOT NULL,
            pytanie_bezpieczenstwa TEXT,
            hash_odpowiedzi TEXT,
            sol_odpowiedzi TEXT,
            utworzono TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS uczniowie (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            korepetytor_id INTEGER NOT NULL,
            imie TEXT NOT NULL,
            nazwisko TEXT,
            telefon TEXT,
            pakiet_godzin REAL NOT NULL DEFAULT 0,
            notatki TEXT,
            utworzono TEXT NOT NULL,
            FOREIGN KEY (korepetytor_id) REFERENCES uzytkownicy (id)
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
    _migruj_baze()


def _napraw_przestarzala_tabele_uczniow():
    """
    Sprawdza, czy tabela 'uczniowie' powstała PRZED wprowadzeniem kont
    użytkowników (czyli nie ma kolumny korepetytor_id). Jeśli tak, usuwa
    ją razem z tabelą 'lekcje' (która i tak się do niej odwołuje), żeby
    mogły zostać utworzone od nowa z poprawną strukturą.

    Uwaga: to nieodwracalnie kasuje uczniów/lekcje zapisane w TEJ starej
    strukturze - ale skoro nie mają nawet przypisanego konta korepetytora,
    i tak nie dałoby się ich sensownie przypisać do nikogo.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='uczniowie'")
    tabela_istnieje = cursor.fetchone() is not None

    if tabela_istnieje:
        cursor.execute("PRAGMA table_info(uczniowie)")
        kolumny = [wiersz["name"] for wiersz in cursor.fetchall()]

        if "korepetytor_id" not in kolumny:
            cursor.execute("DROP TABLE IF EXISTS lekcje")
            cursor.execute("DROP TABLE IF EXISTS uczniowie")
            conn.commit()

    conn.close()


def _migruj_baze():
    """
    Dodaje kolumny do istniejących tabel, jeśli powstały przed wprowadzeniem
    tej funkcji (np. przy aktualizacji aplikacji na już działającej bazie).
    SQLite nie ma "ADD COLUMN IF NOT EXISTS", więc łapiemy błąd, jeśli kolumna
    już istnieje - to nie jest wtedy prawdziwy problem.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE uczniowie ADD COLUMN notatki TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # kolumna już istnieje - nic do zrobienia

    for kolumna, typ in [
        ("pytanie_bezpieczenstwa", "TEXT"),
        ("hash_odpowiedzi", "TEXT"),
        ("sol_odpowiedzi", "TEXT"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE uzytkownicy ADD COLUMN {kolumna} {typ}")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # kolumna już istnieje - nic do zrobienia

    conn.close()


# --- HASŁA (haszowanie z solą) ---

def _hash_password(password, sol=None):
    """Haszuje hasło z solą (PBKDF2). Zwraca (hash, sol)."""
    if sol is None:
        sol = secrets.token_hex(16)
    hash_bytes = hashlib.pbkdf2_hmac("sha256", password.encode(), sol.encode(), 100_000)
    return hash_bytes.hex(), sol


# --- UŻYTKOWNICY (konta korepetytorów) ---

def create_user(login, password, pytanie_bezpieczenstwa, odpowiedz_bezpieczenstwa):
    """
    Tworzy nowe konto wraz z pytaniem i odpowiedzią bezpieczeństwa (do resetu hasła).
    Zwraca id nowego użytkownika.
    Rzuca ValueError, jeśli login jest już zajęty.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM uzytkownicy WHERE login = ?", (login,))
    if cursor.fetchone() is not None:
        conn.close()
        raise ValueError("Ten login jest już zajęty.")

    hash_hasla, sol = _hash_password(password)
    # Odpowiedź na pytanie bezpieczeństwa haszujemy tak samo jak hasło,
    # a przed haszowaniem normalizujemy (mała litera, bez spacji na końcach),
    # żeby drobne różnice w pisowni (wielkość liter) nie blokowały resetu
    hash_odp, sol_odp = _hash_password(odpowiedz_bezpieczenstwa.strip().lower())

    cursor.execute(
        """INSERT INTO uzytkownicy
           (login, hash_hasla, sol, pytanie_bezpieczenstwa, hash_odpowiedzi, sol_odpowiedzi, utworzono)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (login, hash_hasla, sol, pytanie_bezpieczenstwa, hash_odp, sol_odp, datetime.now().isoformat())
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id


def verify_user(login, password):
    """
    Sprawdza dane logowania.
    Zwraca id użytkownika jeśli poprawne, None jeśli nie.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, hash_hasla, sol FROM uzytkownicy WHERE login = ?", (login,))
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None

    proby_hash, _ = _hash_password(password, row["sol"])
    if proby_hash == row["hash_hasla"]:
        return row["id"]
    return None


def get_security_question(login):
    """Zwraca pytanie bezpieczeństwa dla danego loginu, albo None jeśli konto nie istnieje."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT pytanie_bezpieczenstwa FROM uzytkownicy WHERE login = ?", (login,))
    row = cursor.fetchone()
    conn.close()
    return row["pytanie_bezpieczenstwa"] if row else None


def verify_security_answer(login, odpowiedz):
    """Sprawdza odpowiedź na pytanie bezpieczeństwa. Zwraca True/False."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT hash_odpowiedzi, sol_odpowiedzi FROM uzytkownicy WHERE login = ?", (login,))
    row = cursor.fetchone()
    conn.close()

    if row is None or row["hash_odpowiedzi"] is None:
        return False

    proby_hash, _ = _hash_password(odpowiedz.strip().lower(), row["sol_odpowiedzi"])
    return proby_hash == row["hash_odpowiedzi"]


def reset_password(login, nowe_haslo):
    """Ustawia nowe hasło dla użytkownika (po pozytywnej weryfikacji odpowiedzi)."""
    hash_hasla, sol = _hash_password(nowe_haslo)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE uzytkownicy SET hash_hasla = ?, sol = ? WHERE login = ?",
        (hash_hasla, sol, login)
    )
    conn.commit()
    conn.close()


def delete_user(korepetytor_id):
    """
    Usuwa konto użytkownika wraz ze wszystkimi jego uczniami i ich lekcjami.
    Kolejność usuwania ma znaczenie: najpierw lekcje, potem uczniowie, na końcu konto.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Usuń lekcje wszystkich uczniów tego korepetytora
    cursor.execute("""
        DELETE FROM lekcje
        WHERE uczen_id IN (SELECT id FROM uczniowie WHERE korepetytor_id = ?)
    """, (korepetytor_id,))

    # Usuń uczniów tego korepetytora
    cursor.execute("DELETE FROM uczniowie WHERE korepetytor_id = ?", (korepetytor_id,))

    # Usuń samo konto
    cursor.execute("DELETE FROM uzytkownicy WHERE id = ?", (korepetytor_id,))

    conn.commit()
    conn.close()


# --- UCZNIOWIE (zawsze filtrowane po korepetytor_id) ---

def add_student(korepetytor_id, imie, nazwisko, telefon, pakiet_godzin, notatki=""):
    """Dodaje nowego ucznia przypisanego do konkretnego korepetytora."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO uczniowie (korepetytor_id, imie, nazwisko, telefon, pakiet_godzin, notatki, utworzono)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (korepetytor_id, imie, nazwisko, telefon, pakiet_godzin, notatki, datetime.now().isoformat())
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id


def get_students(korepetytor_id):
    """Zwraca uczniów należących wyłącznie do danego korepetytora."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM uczniowie WHERE korepetytor_id = ? ORDER BY imie",
        (korepetytor_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_student_by_id(uczen_id, korepetytor_id):
    """
    Zwraca dane ucznia, ale TYLKO jeśli należy do podanego korepetytora.
    Zwraca None, jeśli uczeń nie istnieje albo należy do kogoś innego —
    to zabezpieczenie przed dostępem do cudzych danych.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM uczniowie WHERE id = ? AND korepetytor_id = ?",
        (uczen_id, korepetytor_id)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def update_student(uczen_id, korepetytor_id, imie, nazwisko, telefon, pakiet_godzin, notatki=""):
    """Aktualizuje dane ucznia — tylko jeśli należy do tego korepetytora."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE uczniowie
           SET imie = ?, nazwisko = ?, telefon = ?, pakiet_godzin = ?, notatki = ?
           WHERE id = ? AND korepetytor_id = ?""",
        (imie, nazwisko, telefon, pakiet_godzin, notatki, uczen_id, korepetytor_id)
    )
    conn.commit()
    conn.close()


def update_student_hours(uczen_id, korepetytor_id, nowa_liczba_godzin):
    """Ustawia nowe saldo godzin — tylko jeśli uczeń należy do tego korepetytora."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE uczniowie SET pakiet_godzin = ? WHERE id = ? AND korepetytor_id = ?",
        (nowa_liczba_godzin, uczen_id, korepetytor_id)
    )
    conn.commit()
    conn.close()


def adjust_student_hours(uczen_id, korepetytor_id, delta):
    """Zmienia saldo godzin ucznia o wartość delta (dodatnia lub ujemna)."""
    student = get_student_by_id(uczen_id, korepetytor_id)
    if student is None:
        raise ValueError("Nie znaleziono ucznia lub brak dostępu.")
    nowe_saldo = student["pakiet_godzin"] + delta
    update_student_hours(uczen_id, korepetytor_id, nowe_saldo)
    return nowe_saldo


def delete_student(uczen_id, korepetytor_id):
    """Usuwa ucznia i jego lekcje — tylko jeśli należy do tego korepetytora."""
    student = get_student_by_id(uczen_id, korepetytor_id)
    if student is None:
        raise ValueError("Nie znaleziono ucznia lub brak dostępu.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM lekcje WHERE uczen_id = ?", (uczen_id,))
    cursor.execute("DELETE FROM uczniowie WHERE id = ? AND korepetytor_id = ?", (uczen_id, korepetytor_id))
    conn.commit()
    conn.close()


# --- LEKCJE (zawsze przez ucznia należącego do korepetytora) ---

def add_lesson(uczen_id, korepetytor_id, data, godzina, czas_trwania=1.0, notatka=""):
    """
    Dodaje nową lekcję i odejmuje godziny z pakietu ucznia.
    Sprawdza najpierw, że uczeń należy do podanego korepetytora.
    """
    student = get_student_by_id(uczen_id, korepetytor_id)
    if student is None:
        raise ValueError("Nie znaleziono ucznia lub brak dostępu.")

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

    adjust_student_hours(uczen_id, korepetytor_id, -czas_trwania)
    return new_id


def get_upcoming_lessons(korepetytor_id):
    """Zwraca zaplanowane lekcje wyłącznie uczniów danego korepetytora."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT lekcje.*, uczniowie.imie, uczniowie.nazwisko
        FROM lekcje
        JOIN uczniowie ON lekcje.uczen_id = uczniowie.id
        WHERE lekcje.status = 'zaplanowana' AND uczniowie.korepetytor_id = ?
        ORDER BY lekcje.data ASC, lekcje.godzina ASC
    """, (korepetytor_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_lessons_by_date_range(korepetytor_id, data_od, data_do):
    """Zwraca lekcje (wszystkie statusy) w zakresie dat, tylko dla danego korepetytora."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT lekcje.*, uczniowie.imie, uczniowie.nazwisko
        FROM lekcje
        JOIN uczniowie ON lekcje.uczen_id = uczniowie.id
        WHERE lekcje.data BETWEEN ? AND ? AND uczniowie.korepetytor_id = ?
        ORDER BY lekcje.data ASC, lekcje.godzina ASC
    """, (data_od, data_do, korepetytor_id))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_lessons_by_student(uczen_id, korepetytor_id):
    """
    Zwraca WSZYSTKIE lekcje danego ucznia (każdy status), od najnowszej do najstarszej.
    Sprawdza najpierw, że uczeń należy do podanego korepetytora.
    """
    student = get_student_by_id(uczen_id, korepetytor_id)
    if student is None:
        raise ValueError("Nie znaleziono ucznia lub brak dostępu.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM lekcje
        WHERE uczen_id = ?
        ORDER BY data DESC, godzina DESC
    """, (uczen_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_all_lessons(korepetytor_id):
    """Zwraca WSZYSTKIE lekcje (każdy status, każda data) dla danego korepetytora."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT lekcje.*, uczniowie.imie, uczniowie.nazwisko
        FROM lekcje
        JOIN uczniowie ON lekcje.uczen_id = uczniowie.id
        WHERE uczniowie.korepetytor_id = ?
        ORDER BY lekcje.data ASC, lekcje.godzina ASC
    """, (korepetytor_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def _get_lesson_with_owner_check(lekcja_id, korepetytor_id):
    """Wewnętrzna funkcja: zwraca lekcję tylko jeśli jej uczeń należy do korepetytora."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT lekcje.* FROM lekcje
        JOIN uczniowie ON lekcje.uczen_id = uczniowie.id
        WHERE lekcje.id = ? AND uczniowie.korepetytor_id = ?
    """, (lekcja_id, korepetytor_id))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def mark_lesson_status(lekcja_id, korepetytor_id, status):
    """Zmienia status lekcji — tylko jeśli należy do korepetytora."""
    lekcja = _get_lesson_with_owner_check(lekcja_id, korepetytor_id)
    if lekcja is None:
        raise ValueError("Nie znaleziono lekcji lub brak dostępu.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE lekcje SET status = ? WHERE id = ?", (status, lekcja_id))
    conn.commit()
    conn.close()


def cancel_lesson(lekcja_id, korepetytor_id):
    """Odwołuje lekcję i zwraca godziny do pakietu ucznia — tylko jeśli należy do korepetytora."""
    lekcja = _get_lesson_with_owner_check(lekcja_id, korepetytor_id)
    if lekcja is None:
        raise ValueError("Nie znaleziono lekcji lub brak dostępu.")

    mark_lesson_status(lekcja_id, korepetytor_id, "odwolana")
    adjust_student_hours(lekcja["uczen_id"], korepetytor_id, lekcja["czas_trwania"])
