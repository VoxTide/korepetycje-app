"""
database.py
Obsługa bazy danych dla systemu rezerwacji korepetycji - lokalnie plik
SQLite, a w chmurze (jeśli skonfigurowane) trwała baza Turso, patrz
db_backend.py.

Struktura:
- uzytkownicy: konta korepetytorów (login, zahaszowane hasło)
- uczniowie: dane ucznia + saldo godzin, powiązane z kontem korepetytora
- lekcje: zaplanowane/odbyte lekcje, powiązane z uczniem
"""

import sqlite3
import hashlib
import secrets
from datetime import datetime, timedelta
import db_backend

DB_NAME = "korepetycje.db"


def get_connection():
    """Zwraca połączenie z bazą danych (Turso w chmurze, jeśli skonfigurowane w sekretach, inaczej lokalny plik)."""
    return db_backend.polacz(DB_NAME)


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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS konta_uczniow (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uczen_id INTEGER NOT NULL UNIQUE,
            login TEXT NOT NULL UNIQUE,
            hash_hasla TEXT NOT NULL,
            sol TEXT NOT NULL,
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
    except Exception:
        pass  # kolumna już istnieje - nic do zrobienia

    for kolumna, typ in [
        ("pytanie_bezpieczenstwa", "TEXT"),
        ("hash_odpowiedzi", "TEXT"),
        ("sol_odpowiedzi", "TEXT"),
        ("email", "TEXT"),
        ("reset_kod", "TEXT"),
        ("reset_wygasa", "TEXT"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE uzytkownicy ADD COLUMN {kolumna} {typ}")
            conn.commit()
        except Exception:
            pass  # kolumna już istnieje - nic do zrobienia

    try:
        cursor.execute("ALTER TABLE uczniowie ADD COLUMN email TEXT")
        conn.commit()
    except Exception:
        pass  # kolumna już istnieje - nic do zrobienia

    try:
        cursor.execute("ALTER TABLE uczniowie ADD COLUMN kod_zaproszenia TEXT")
        conn.commit()
    except Exception:
        pass  # kolumna już istnieje - nic do zrobienia

    try:
        cursor.execute("ALTER TABLE lekcje ADD COLUMN notatka_ucznia TEXT")
        conn.commit()
    except Exception:
        pass  # kolumna już istnieje - nic do zrobienia

    # Uczniowie dodani PRZED wprowadzeniem kont uczniowskich nie mają jeszcze
    # kodu zaproszenia - dogenerowujemy go, żeby mogli założyć konto
    cursor.execute("SELECT id FROM uczniowie WHERE kod_zaproszenia IS NULL")
    do_uzupelnienia = cursor.fetchall()
    for wiersz in do_uzupelnienia:
        cursor.execute(
            "UPDATE uczniowie SET kod_zaproszenia = ? WHERE id = ?",
            (_wygeneruj_kod_zaproszenia(), wiersz["id"])
        )
    if do_uzupelnienia:
        conn.commit()

    conn.close()


# --- HASŁA (haszowanie z solą) ---

def _wygeneruj_kod_zaproszenia():
    """Generuje krótki, czytelny kod zaproszenia dla ucznia (np. 8A3F9K2C)."""
    znaki = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # bez znaków łatwych do pomylenia (0/O, 1/I)
    return "".join(secrets.choice(znaki) for _ in range(8))


def _hash_password(password, sol=None):
    """Haszuje hasło z solą (PBKDF2). Zwraca (hash, sol)."""
    if sol is None:
        sol = secrets.token_hex(16)
    hash_bytes = hashlib.pbkdf2_hmac("sha256", password.encode(), sol.encode(), 100_000)
    return hash_bytes.hex(), sol


# --- UŻYTKOWNICY (konta korepetytorów) ---

def create_user(login, password, email):
    """
    Tworzy nowe konto z adresem e-mail (potrzebnym do resetu hasła).
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

    cursor.execute(
        """INSERT INTO uzytkownicy (login, hash_hasla, sol, email, utworzono)
           VALUES (?, ?, ?, ?, ?)""",
        (login, hash_hasla, sol, email, datetime.now().isoformat())
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


def get_user_email(login):
    """Zwraca adres e-mail przypisany do konta, albo None jeśli konto nie istnieje lub nie ma e-maila."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT email FROM uzytkownicy WHERE login = ?", (login,))
    row = cursor.fetchone()
    conn.close()
    return row["email"] if row else None


def wygeneruj_kod_resetu(login):
    """
    Generuje 6-cyfrowy kod resetu hasła, ważny 15 minut, i zapisuje go w bazie.
    Zwraca wygenerowany kod (do wysłania e-mailem) albo None, jeśli konto nie istnieje.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM uzytkownicy WHERE login = ?", (login,))
    if cursor.fetchone() is None:
        conn.close()
        return None

    kod = f"{secrets.randbelow(1_000_000):06d}"
    wygasa = (datetime.now() + timedelta(minutes=15)).isoformat()

    cursor.execute(
        "UPDATE uzytkownicy SET reset_kod = ?, reset_wygasa = ? WHERE login = ?",
        (kod, wygasa, login)
    )
    conn.commit()
    conn.close()
    return kod


def zweryfikuj_kod_resetu(login, podany_kod):
    """Sprawdza, czy podany kod resetu jest poprawny i nie wygasł."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT reset_kod, reset_wygasa FROM uzytkownicy WHERE login = ?", (login,))
    row = cursor.fetchone()
    conn.close()

    if row is None or row["reset_kod"] is None:
        return False
    if row["reset_kod"] != podany_kod.strip():
        return False
    if datetime.now() > datetime.fromisoformat(row["reset_wygasa"]):
        return False
    return True


def wyczysc_kod_resetu(login):
    """Kasuje zużyty/wygasły kod resetu, żeby nie dało się go użyć ponownie."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE uzytkownicy SET reset_kod = NULL, reset_wygasa = NULL WHERE login = ?",
        (login,)
    )
    conn.commit()
    conn.close()


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

def add_student(korepetytor_id, imie, nazwisko, telefon, pakiet_godzin, notatki="", email=""):
    """Dodaje nowego ucznia przypisanego do konkretnego korepetytora, z wygenerowanym kodem zaproszenia."""
    conn = get_connection()
    cursor = conn.cursor()
    kod = _wygeneruj_kod_zaproszenia()
    cursor.execute(
        """INSERT INTO uczniowie
           (korepetytor_id, imie, nazwisko, telefon, pakiet_godzin, notatki, email, kod_zaproszenia, utworzono)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (korepetytor_id, imie, nazwisko, telefon, pakiet_godzin, notatki, email, kod, datetime.now().isoformat())
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


def update_student(uczen_id, korepetytor_id, imie, nazwisko, telefon, pakiet_godzin, notatki="", email=""):
    """Aktualizuje dane ucznia — tylko jeśli należy do tego korepetytora."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE uczniowie
           SET imie = ?, nazwisko = ?, telefon = ?, pakiet_godzin = ?, notatki = ?, email = ?
           WHERE id = ? AND korepetytor_id = ?""",
        (imie, nazwisko, telefon, pakiet_godzin, notatki, email, uczen_id, korepetytor_id)
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


def _status_rezerwuje_godziny(status):
    """
    'zaplanowana' i 'odbyta' oznaczają, że godziny są odjęte z pakietu ucznia.
    'odwolana' oznacza, że godziny zostały zwrócone. Używane do wyliczenia,
    czy zmiana statusu wymaga odjęcia albo oddania godzin.
    """
    return status in ("zaplanowana", "odbyta")


def change_lesson_status_manual(lekcja_id, korepetytor_id, nowy_status):
    """
    Ręcznie ustawia dowolny status lekcji (zaplanowana / odbyta / odwolana),
    automatycznie korygując saldo godzin ucznia, żeby zawsze było spójne
    niezależnie od tego, z jakiego stanu w jaki przechodzimy - np. cofnięcie
    z „odwołana” z powrotem na „zaplanowana” ponownie odejmuje godziny.
    """
    lekcja = _get_lesson_with_owner_check(lekcja_id, korepetytor_id)
    if lekcja is None:
        raise ValueError("Nie znaleziono lekcji lub brak dostępu.")

    stary_status = lekcja["status"]
    if stary_status == nowy_status:
        return  # nic się nie zmienia

    stary_rezerwowal = _status_rezerwuje_godziny(stary_status)
    nowy_rezerwuje = _status_rezerwuje_godziny(nowy_status)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE lekcje SET status = ? WHERE id = ?", (nowy_status, lekcja_id))
    conn.commit()
    conn.close()

    if stary_rezerwowal and not nowy_rezerwuje:
        adjust_student_hours(lekcja["uczen_id"], korepetytor_id, lekcja["czas_trwania"])
    elif not stary_rezerwowal and nowy_rezerwuje:
        adjust_student_hours(lekcja["uczen_id"], korepetytor_id, -lekcja["czas_trwania"])


def delete_lesson(lekcja_id, korepetytor_id):
    """
    Usuwa lekcję na stałe (bez śladu w historii) - tylko jeśli należy do
    korepetytora. Jeśli lekcja miała zarezerwowane godziny (zaplanowana albo
    odbyta), zwraca je do pakietu ucznia przed usunięciem, żeby usunięcie nie
    zostawiło ucznia z zaniżonym saldem za coś, czego już nie widać w systemie.
    """
    lekcja = _get_lesson_with_owner_check(lekcja_id, korepetytor_id)
    if lekcja is None:
        raise ValueError("Nie znaleziono lekcji lub brak dostępu.")

    if _status_rezerwuje_godziny(lekcja["status"]):
        adjust_student_hours(lekcja["uczen_id"], korepetytor_id, lekcja["czas_trwania"])

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM lekcje WHERE id = ?", (lekcja_id,))
    conn.commit()
    conn.close()


# --- KONTA UCZNIÓW (osobny system logowania, niezależny od kont korepetytorów) ---

def get_invite_code(uczen_id, korepetytor_id):
    """Zwraca kod zaproszenia ucznia — tylko jeśli należy do tego korepetytora."""
    uczen = get_student_by_id(uczen_id, korepetytor_id)
    return uczen["kod_zaproszenia"] if uczen else None


def czy_uczen_ma_konto(uczen_id):
    """Sprawdza, czy dany uczeń już założył sobie konto."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM konta_uczniow WHERE uczen_id = ?", (uczen_id,))
    istnieje = cursor.fetchone() is not None
    conn.close()
    return istnieje


def stworz_konto_ucznia(kod_zaproszenia, login, haslo):
    """
    Zakłada konto uczniowskie na podstawie kodu zaproszenia otrzymanego od korepetytora.
    Zwraca id nowego konta. Rzuca ValueError przy nieprawidłowym kodzie, zajętym
    loginie, albo jeśli dany uczeń już ma założone konto.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM uczniowie WHERE kod_zaproszenia = ?", (kod_zaproszenia.strip().upper(),))
    uczen = cursor.fetchone()
    if uczen is None:
        conn.close()
        raise ValueError("Nieprawidłowy kod zaproszenia.")

    uczen_id = uczen["id"]

    cursor.execute("SELECT id FROM konta_uczniow WHERE uczen_id = ?", (uczen_id,))
    if cursor.fetchone() is not None:
        conn.close()
        raise ValueError("Dla tego ucznia istnieje już założone konto.")

    cursor.execute("SELECT id FROM konta_uczniow WHERE login = ?", (login,))
    if cursor.fetchone() is not None:
        conn.close()
        raise ValueError("Ten login jest już zajęty.")

    hash_hasla, sol = _hash_password(haslo)
    cursor.execute(
        """INSERT INTO konta_uczniow (uczen_id, login, hash_hasla, sol, utworzono)
           VALUES (?, ?, ?, ?, ?)""",
        (uczen_id, login, hash_hasla, sol, datetime.now().isoformat())
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id


def verify_student(login, haslo):
    """Sprawdza dane logowania ucznia. Zwraca uczen_id jeśli poprawne, None jeśli nie."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT uczen_id, hash_hasla, sol FROM konta_uczniow WHERE login = ?", (login,))
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None

    proby_hash, _ = _hash_password(haslo, row["sol"])
    if proby_hash == row["hash_hasla"]:
        return row["uczen_id"]
    return None


def get_student_own_profile(uczen_id):
    """
    Zwraca dane ucznia bez sprawdzania właściciela (korepetytora) - używane
    WYŁĄCZNIE do pokazania uczniowi jego własnych danych po zalogowaniu na
    jego konto, gdzie uczen_id pochodzi z jego własnej, zweryfikowanej sesji.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM uczniowie WHERE id = ?", (uczen_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_own_upcoming_lessons(uczen_id):
    """Zwraca zaplanowane lekcje danego ucznia - do użytku w jego własnym, zalogowanym widoku."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM lekcje
        WHERE uczen_id = ? AND status = 'zaplanowana'
        ORDER BY data ASC, godzina ASC
    """, (uczen_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_own_lesson_history(uczen_id):
    """Zwraca WSZYSTKIE lekcje danego ucznia (każdy status) - do jego własnego widoku historii."""
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


def update_student_lesson_note(lekcja_id, uczen_id, notatka_ucznia):
    """
    Zapisuje notatkę ucznia do konkretnej lekcji - tylko jeśli lekcja należy
    do tego ucznia (sprawdzenie przez uczen_id z jego własnej sesji logowania).
    To osobne pole od notatki korepetytora - żadne z nich nie nadpisuje drugiego.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM lekcje WHERE id = ? AND uczen_id = ?", (lekcja_id, uczen_id))
    if cursor.fetchone() is None:
        conn.close()
        raise ValueError("Nie znaleziono lekcji lub brak dostępu.")

    cursor.execute("UPDATE lekcje SET notatka_ucznia = ? WHERE id = ?", (notatka_ucznia, lekcja_id))
    conn.commit()
    conn.close()


def delete_own_student_account(uczen_id):
    """
    Usuwa WYŁĄCZNIE login/hasło ucznia (wiersz w konta_uczniow) - nie rusza
    jego rekordu w tabeli uczniowie ani historii lekcji, bo te dane należą
    do korepetytora i muszą zostać. Po usunięciu logowania stary kod
    zaproszenia znów staje się aktywny, więc uczeń (albo ktoś inny) może
    ponownie założyć konto, jeśli zechce.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM konta_uczniow WHERE uczen_id = ?", (uczen_id,))
    conn.commit()
    conn.close()


def cancel_lesson_by_student(lekcja_id, uczen_id):
    """
    Pozwala uczniowi odwołać SWOJĄ własną, zaplanowaną lekcję - bez znajomości
    korepetytor_id (uczeń nie ma do niego dostępu, więc nie może korzystać
    z cancel_lesson). Sprawdzenie własności odbywa się przez uczen_id, które
    pochodzi z jego własnej, zweryfikowanej sesji logowania.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM lekcje WHERE id = ? AND uczen_id = ?", (lekcja_id, uczen_id))
    lekcja = cursor.fetchone()

    if lekcja is None:
        conn.close()
        raise ValueError("Nie znaleziono lekcji lub brak dostępu.")
    if lekcja["status"] != "zaplanowana":
        conn.close()
        raise ValueError("Można odwołać tylko zaplanowaną lekcję.")

    cursor.execute("UPDATE lekcje SET status = 'odwolana' WHERE id = ?", (lekcja_id,))
    cursor.execute(
        "UPDATE uczniowie SET pakiet_godzin = pakiet_godzin + ? WHERE id = ?",
        (lekcja["czas_trwania"], uczen_id)
    )
    conn.commit()
    conn.close()
